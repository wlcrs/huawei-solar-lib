"""Low-level Modbus logic."""

import asyncio
import logging
from typing import TypeVar

import tenacity
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_fixed,
)
from tmodbus import AsyncModbusClient, AsyncRtuTransport, AsyncSmartTransport, AsyncTcpTransport
from tmodbus.exceptions import ModbusResponseError, TModbusError
from tmodbus.utils.crc import calculate_crc16

from .exceptions import ReadException
from .modbus_pdu import (
    CompleteUploadPDU,
    LoginPDU,
    LoginRequestChallengePDU,
    StartFileUploadPDU,
    UploadFileFramePDU,
)
from .register_client import RegisterAwareModbusClient

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
RT = TypeVar("RT")


DEFAULT_TCP_PORT = 502
DEFAULT_BAUDRATE = 9600

DEFAULT_UNIT_ID = 0
DEFAULT_TIMEOUT = 10  # especially the SDongle can react quite slowly
DEFAULT_SCAN_TIMEOUT = 3  # short timeout for scanning — responding devices reply in milliseconds
DEFAULT_WAIT = 1
DEFAULT_COOLDOWN_TIME = 0.05
WAIT_FOR_CONNECTION_TIMEOUT = 5
WAIT_FOR_LOGIN_TIMEOUT = 5

HEARTBEAT_REGISTER = 49999

FILE_UPLOAD_MAX_RETRIES = 6
FILE_UPLOAD_RETRY_TIMEOUT = 10


RECONNECT_RETRY_STRATEGY = AsyncRetrying(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    # Stop trying to reconnect if the connection has not been re-established within 1 minute
    stop=stop_after_delay(60),
    after=lambda retry_call_state: _LOGGER.debug(
        "Backing off before reconnect for %0.1fs after %d tries",
        retry_call_state.upcoming_sleep,
        retry_call_state.attempt_number,
    ),
)


def log_invalid_response(retry_state: "tenacity.RetryCallState") -> None:
    """Log an invalid response."""
    if retry_state.outcome:
        if e := retry_state.outcome.exception():
            _LOGGER.debug(
                "Backing off for %0.1fs after exception response %s",
                retry_state.upcoming_sleep,
                e,
            )
        else:
            _LOGGER.debug(
                "Backing off for %0.1fs after invalid response %s",
                retry_state.upcoming_sleep,
                retry_state.outcome.result(),
            )
    else:
        _LOGGER.debug(
            "Backing off for %0.1fs before retrying request",
            retry_state.upcoming_sleep,
        )


RESPONSE_RETRY_STRATEGY = AsyncRetrying(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    # Retry up to 3 times on invalid response
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(TimeoutError),
    reraise=True,
    after=log_invalid_response,
)

# No retries for scanning: if a device doesn't respond on the first attempt, it's not there.
SCAN_RESPONSE_RETRY_STRATEGY = AsyncRetrying(
    wait=wait_fixed(1),
    stop=stop_after_attempt(2),
    reraise=True,
)


class AsyncHuaweiSolarClient(RegisterAwareModbusClient, AsyncModbusClient):
    """Async client to Huawei Solar devices."""

    def for_unit_id(self, unit_id: int) -> "AsyncHuaweiSolarClient":
        """Get a copy of this client for a different unit ID."""
        if unit_id == self.unit_id:
            return self
        return AsyncHuaweiSolarClient(self.transport, unit_id=unit_id, word_order=self.word_order)

    async def get_file(
        self,
        file_type: int,
        customized_data: bytes | None = None,
    ) -> bytes:
        """Read a 'file' via Modbus.

        As defined by the 'Uploading Files' process described in 6.3.7.1 of
        the Solar Inverter Modbus Interface Definitions PDF.
        """
        _LOGGER.debug(
            "Reading file %#x from server %d",
            file_type,
            self.unit_id,
        )
        # Start the upload
        start_upload_response = await self.execute(
            StartFileUploadPDU(
                file_type=file_type,
                customised_data=customized_data or b"",
            ),
        )

        file_length = start_upload_response.file_length
        data_frame_length = start_upload_response.data_frame_length

        # Request the data in 'frames'

        file_data: bytes = b""
        next_frame_no = 0

        while (next_frame_no * data_frame_length) < file_length:
            data_upload_response = await self.execute(
                UploadFileFramePDU(file_type=file_type, frame_no=next_frame_no),
            )

            file_data += data_upload_response.frame_data
            next_frame_no += 1

        # Complete the upload and check the CRC
        file_crc = await self.execute(
            CompleteUploadPDU(file_type=file_type),
        )

        # swap upper and lower two bytes to match how computeCRC works
        swapped_crc = ((file_crc << 8) & 0xFF00) | ((file_crc >> 8) & 0x00FF)

        if (calculated_crc := int.from_bytes(calculate_crc16(file_data))) != swapped_crc:
            msg = (
                f"Computed CRC {calculated_crc:04x} for file {file_type} "
                f"does not match expected value {swapped_crc:04x}"
            )
            raise ReadException(msg)

        return file_data

    async def login(self, username: str, password: str) -> bool:
        """Login onto the inverter."""
        _LOGGER.debug("Logging in '%s'", username)
        # this circumvents the locking issue when using self.execute which locks on
        # _communication_lock in AsyncSmartTransport.send_and_receive
        assert isinstance(self.transport, AsyncSmartTransport)
        inverter_challenge = await self.transport.base_transport.send_and_receive(
            self.unit_id,
            LoginRequestChallengePDU(),
        )

        logged_in = await self.transport.base_transport.send_and_receive(
            self.unit_id,
            LoginPDU(username, password, inverter_challenge),
        )
        if logged_in:
            # Make sure we re-login after a reconnect
            assert isinstance(self.transport, AsyncSmartTransport)

            async def login_on_reconnect() -> None:
                """Login again after a reconnect."""
                _LOGGER.info("Reconnected to inverter, logging in again")
                logged_in_again = await self.login(username, password)
                if not logged_in_again:
                    _LOGGER.error("Failed to login after reconnect. Will not try again")
                    assert isinstance(self.transport, AsyncSmartTransport)
                    self.transport.on_reconnected = None
                else:
                    _LOGGER.info("Successfully logged in again after reconnect")

            async def login_on_reconnect_with_timeout() -> None:
                """Login again after a reconnect, with timeout."""
                return await asyncio.wait_for(login_on_reconnect(), timeout=WAIT_FOR_LOGIN_TIMEOUT)

            self.transport.on_reconnected = login_on_reconnect_with_timeout

        return logged_in

    async def heartbeat(self) -> bool:
        """Perform the heartbeat command. Only useful when maintaining a session."""
        if not self.connected:
            return False
        try:
            # 49999 is the magic register used to keep the connection alive
            await self.write_single_register(
                HEARTBEAT_REGISTER,
                0x1,
            )
        except ModbusResponseError as e:
            _LOGGER.warning("Received an error response when writing to the heartbeat register: %02x", e.error_code)
            return False
        except TModbusError:
            _LOGGER.exception("Exception during heartbeat")
            return False
        else:
            _LOGGER.debug("Heartbeat succeeded")
            return True


def create_client(
    transport: AsyncTcpTransport | AsyncRtuTransport,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = 1.0,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolar instance."""
    # Wrap the transport in a smart transport to add auto-reconnect and cooldown between requests

    smart_transport = AsyncSmartTransport(
        transport,
        auto_reconnect=RECONNECT_RETRY_STRATEGY,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        response_retry_strategy=RESPONSE_RETRY_STRATEGY,
        retry_on_device_busy=True,
        retry_on_device_failure=True,
    )
    return AsyncHuaweiSolarClient(smart_transport, unit_id=unit_id)


def create_scan_client(
    transport: AsyncTcpTransport | AsyncRtuTransport,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = 1.0,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient optimized for device scanning.

    Uses no retries so non-responding unit IDs are skipped quickly instead of
    being retried multiple times with backoff.
    """
    smart_transport = AsyncSmartTransport(
        transport,
        auto_reconnect=RECONNECT_RETRY_STRATEGY,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        response_retry_strategy=SCAN_RESPONSE_RETRY_STRATEGY,
    )
    return AsyncHuaweiSolarClient(smart_transport, unit_id=unit_id)


def create_tcp_client(
    host: str,
    port: int = DEFAULT_TCP_PORT,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    timeout: int = DEFAULT_TIMEOUT,
    wait_after_connect: float = 1.0,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient connected via TCP."""
    transport = AsyncTcpTransport(host, port, timeout=timeout)
    return create_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
    )


def create_scan_tcp_client(
    host: str,
    port: int = DEFAULT_TCP_PORT,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    timeout: int = DEFAULT_SCAN_TIMEOUT,
    wait_after_connect: float = 1.0,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient optimized for TCP device scanning."""
    transport = AsyncTcpTransport(host, port, timeout=timeout)
    return create_scan_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
    )


def create_rtu_client(
    port: str,
    *,
    baudrate: int = DEFAULT_BAUDRATE,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = 1.0,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient connected via RTU."""
    transport = AsyncRtuTransport(port, baudrate=baudrate)
    return create_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
    )


def create_scan_rtu_client(
    port: str,
    *,
    baudrate: int = DEFAULT_BAUDRATE,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = 1.0,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient optimized for RTU device scanning."""
    transport = AsyncRtuTransport(port, baudrate=baudrate)
    return create_scan_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
    )
