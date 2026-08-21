"""Low-level Modbus logic."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
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
from tmodbus.exceptions import ModbusConnectionError, ModbusResponseError, TModbusError
from tmodbus.pdu.base import BaseClientPDU
from tmodbus.utils.crc import calculate_crc16

from .const import MAX_PDU_SIZE
from .exceptions import ConnectionInterruptedException, DecodeError, ReadException
from .modbus_pdu import (
    CompleteUploadPDU,
    LoginPDU,
    LoginRequestChallengePDU,
    MultiDeviceRegisterReadPDU,
    MultiRegisterReadPDU,
    QueryDeviceLogicAddressListPDU,
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
DEFAULT_WAIT_AFTER_CONNECT = 1.0
DEFAULT_COOLDOWN_TIME = 0.05
DEFAULT_MAX_CONSECUTIVE_TIMEOUTS = 5
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


class TimeoutAwareSmartTransport(AsyncSmartTransport):
    """Smart transport that forces a reconnect after repeated timeouts."""

    def __init__(  # noqa: PLR0913
        self,
        base_transport: AsyncTcpTransport | AsyncRtuTransport,
        *,
        consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
        wait_between_requests: float = 0.0,
        wait_after_connect: float = 0.0,
        auto_reconnect: bool | AsyncRetrying = True,
        on_reconnected: Callable[[], Awaitable[None] | None] | None = None,
        on_connection_lost: Callable[[Exception | None], None] | None = None,
        response_retry_strategy: AsyncRetrying | None = None,
        retry_on_device_busy: bool = True,
        retry_on_device_failure: bool = False,
    ) -> None:
        """Initialize the timeout-aware smart transport."""
        self.consecutive_timeouts_before_reconnect = consecutive_timeouts_before_reconnect
        self._consecutive_timeouts = 0
        super().__init__(
            base_transport,
            wait_between_requests=wait_between_requests,
            wait_after_connect=wait_after_connect,
            auto_reconnect=auto_reconnect,
            on_reconnected=on_reconnected,
            on_connection_lost=on_connection_lost,
            response_retry_strategy=response_retry_strategy,
            retry_on_device_busy=retry_on_device_busy,
            retry_on_device_failure=retry_on_device_failure,
        )

        # reset the amount of consecutive timeouts after reconnecting
        base_on_reconnected = self.on_reconnected

        def reset_timeouts_count_on_reconnected() -> None:
            """Reset the consecutive timeouts count on reconnect."""
            self._consecutive_timeouts = 0
            if base_on_reconnected:
                base_on_reconnected()

        self.on_reconnected = reset_timeouts_count_on_reconnected

    async def send_and_receive(self, unit_id: int, pdu: BaseClientPDU[RT]) -> RT:
        """Send a request and force a reconnect after repeated timeouts."""
        try:
            response: RT = await super().send_and_receive(unit_id, pdu)
        except TimeoutError:
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= self.consecutive_timeouts_before_reconnect:
                _LOGGER.warning(
                    "Reached %d consecutive timeouts; forcing reconnect on the next request",
                    self._consecutive_timeouts,
                )
                self._must_reconnect = True
            raise
        else:
            self._consecutive_timeouts = 0
            return response


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
        try:
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

        except ModbusResponseError as err:
            msg = f"Failed to read file {file_type:#x}: received {type(err).__name__}"
            raise ReadException(msg, modbus_exception_code=err.error_code) from err
        except ModbusConnectionError as err:
            _LOGGER.exception("Connection error while reading file %#x", file_type)
            msg = f"Connection failed when trying to read file {file_type:#x}"
            raise ConnectionInterruptedException(msg) from err
        except TModbusError as err:
            msg = f"Failed to read file {file_type:#x}: {err}"
            raise ReadException(msg) from err
        else:
            # swap upper and lower two bytes to match how computeCRC works
            swapped_crc = ((file_crc << 8) & 0xFF00) | ((file_crc >> 8) & 0x00FF)

            if (calculated_crc := int.from_bytes(calculate_crc16(file_data))) != swapped_crc:
                msg = (
                    f"Computed CRC {calculated_crc:04x} for file {file_type} "
                    f"does not match expected value {swapped_crc:04x}"
                )
                raise DecodeError(msg)

            return file_data

    async def login(self, username: str, password: str) -> bool:
        """Login onto the inverter."""
        _LOGGER.debug("Logging in '%s'", username)
        # this circumvents the locking issue when using self.execute which locks on
        # _communication_lock in AsyncSmartTransport.send_and_receive
        assert isinstance(self.transport, AsyncSmartTransport)
        try:
            inverter_challenge = await self.transport.base_transport.send_and_receive(
                self.unit_id,
                LoginRequestChallengePDU(),
            )

            logged_in = await self.transport.base_transport.send_and_receive(
                self.unit_id,
                LoginPDU(username, password, inverter_challenge),
            )
        except ModbusResponseError as err:
            msg = f"Failed to login: received {type(err).__name__}"
            raise ReadException(msg, modbus_exception_code=err.error_code) from err
        except ModbusConnectionError as err:
            _LOGGER.exception("Connection error while logging in")
            msg = "Connection failed when trying to login"
            raise ConnectionInterruptedException(msg) from err
        except TModbusError as err:
            msg = f"Failed to login: {err}"
            raise ReadException(msg) from err

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

    async def query_device_logic_address_list(self, unit_id: int = DEFAULT_UNIT_ID) -> list[int]:
        """Query the list of connected device logic addresses using custom PDU 0x41 0x38.

        Used to discover all active slave logic addresses (Unit IDs) on a bus/loop
        connected to a SmartLogger or Dongle gateway.

        Args:
            unit_id: The target gateway/inverter Unit ID to query (default 0).
                Typically sent to broadcast (0) or the primary SmartLogger address.

        Returns:
            A list of detected slave unit IDs (e.g. ``[1, 2, 16]``).

        Raises:
            ReadException: If the device returns a Modbus exception or malformed payload.
            ConnectionInterruptedException: If connection is lost during communication.

        """
        pdu = QueryDeviceLogicAddressListPDU()
        try:
            return await self.for_unit_id(unit_id).execute(pdu)
        except ModbusResponseError as err:
            msg = f"Failed to query device logic address list: received {type(err).__name__}"
            raise ReadException(msg, modbus_exception_code=err.error_code) from err
        except ModbusConnectionError as err:
            _LOGGER.exception("Connection error while querying device logic address list")
            msg = "Connection failed when trying to query device logic address list"
            raise ConnectionInterruptedException(msg) from err
        except TModbusError as err:
            msg = f"Failed to query device logic address list: {err}"
            raise ReadException(msg) from err

    async def multi_register_read(
        self,
        registers: list[tuple[int, int]],
        unit_id: int | None = None,
    ) -> dict[int, bytes]:
        """Perform a multi-register read using custom PDU 0x41 0x33.

        Allows querying arbitrary, non-contiguous register addresses in request
        frames, avoiding the need to query multiple contiguous ranges or intermediate
        dummy gap registers.

        If the number of requested registers exceeds the maximum Modbus PDU payload
        size (~253 bytes), this method automatically splits the query into multiple
        consecutive requests and merges the results.

        Args:
            registers: List of ``(register_address, register_length_in_words)`` tuples
                to fetch (e.g. ``[(30000, 15), (32089, 1), (37100, 2)]``).
            unit_id: Target unit ID. If None, uses ``self.unit_id``.

        Returns:
            Dictionary mapping ``register_address`` (int) to raw data bytes (bytes).

        Limitations:
            - If connected through a third-party gateway that blocks FC 0x41,
              a standard FC 0x03 read must be used instead.

        Raises:
            ReadException: If the device returns a Modbus exception or missing register data.
            ConnectionInterruptedException: If connection is lost during communication.

        """
        target_client = self if unit_id is None else self.for_unit_id(unit_id)

        chunks: list[list[tuple[int, int]]] = []
        current_chunk: list[tuple[int, int]] = []
        current_req_len = 5
        current_resp_len = 5
        for reg_addr, reg_len in registers:
            item_req = 3
            item_resp = 3 + (reg_len * 2)
            if current_chunk and (
                current_req_len + item_req > MAX_PDU_SIZE
                or current_resp_len + item_resp > MAX_PDU_SIZE
            ):
                chunks.append(current_chunk)
                current_chunk = []
                current_req_len = 5
                current_resp_len = 5
            current_chunk.append((reg_addr, reg_len))
            current_req_len += item_req
            current_resp_len += item_resp
        if current_chunk:
            chunks.append(current_chunk)

        combined_results: dict[int, bytes] = {}
        for frame_no, chunk in enumerate(chunks):
            pdu = MultiRegisterReadPDU(registers=chunk, frame_no=frame_no & 0xFF)
            try:
                chunk_res = await target_client.execute(pdu)
            except ModbusResponseError as err:
                msg = f"Failed to perform multi-register read: received {type(err).__name__}"
                raise ReadException(msg, modbus_exception_code=err.error_code) from err
            except ModbusConnectionError as err:
                _LOGGER.exception("Connection error during multi-register read")
                msg = "Connection failed when trying to perform multi-register read"
                raise ConnectionInterruptedException(msg) from err
            except TModbusError as err:
                msg = f"Failed to perform multi-register read: {err}"
                raise ReadException(msg) from err
            combined_results.update(chunk_res)

        return combined_results

    async def multi_device_register_read(
        self,
        items: list[tuple[int, int, int]],
        unit_id: int = DEFAULT_UNIT_ID,
    ) -> dict[tuple[int, int], bytes]:
        """Perform a multi-device multi-register read using custom PDU 0x41 0x37.

        Allows fetching registers from multiple cascaded Modbus slave devices
        (inverters, meters, batteries, sensors) in request frames.

        If the number of requested items exceeds the maximum Modbus PDU payload
        size (~253 bytes), this method automatically splits the query into multiple
        consecutive requests and merges the results.

        Args:
            items: List of ``(unit_id, register_address, register_length_in_words)``
                tuples to fetch across connected slave devices.
            unit_id: The gateway/master device Unit ID receiving the aggregated
                request (default 0).

        Returns:
            Dictionary mapping ``(unit_id, register_address)`` to raw data bytes.

        Limitations:
            - Applicable when connected through a master gateway/SmartLogger
              managing multiple RS485 slave devices.

        Raises:
            ReadException: If the device returns a Modbus exception or communication fails.
            ConnectionInterruptedException: If connection is lost during communication.

        """
        chunks: list[list[tuple[int, int, int]]] = []
        current_chunk: list[tuple[int, int, int]] = []
        current_req_len = 5
        current_resp_len = 5
        for u_id, reg_addr, reg_len in items:
            item_req = 4
            item_resp = 4 + (reg_len * 2)
            if current_chunk and (
                current_req_len + item_req > MAX_PDU_SIZE
                or current_resp_len + item_resp > MAX_PDU_SIZE
            ):
                chunks.append(current_chunk)
                current_chunk = []
                current_req_len = 5
                current_resp_len = 5
            current_chunk.append((u_id, reg_addr, reg_len))
            current_req_len += item_req
            current_resp_len += item_resp
        if current_chunk:
            chunks.append(current_chunk)

        target_client = self if (unit_id is None or unit_id == self.unit_id) else self.for_unit_id(unit_id)
        combined_results: dict[tuple[int, int], bytes] = {}
        for frame_no, chunk in enumerate(chunks):
            pdu = MultiDeviceRegisterReadPDU(items=chunk, frame_no=frame_no & 0xFF)
            try:
                chunk_res = await target_client.execute(pdu)
            except ModbusResponseError as err:
                msg = f"Failed to perform multi-device register read: received {type(err).__name__}"
                raise ReadException(msg, modbus_exception_code=err.error_code) from err
            except ModbusConnectionError as err:
                _LOGGER.exception("Connection error during multi-device register read")
                msg = "Connection failed when trying to perform multi-device register read"
                raise ConnectionInterruptedException(msg) from err
            except TModbusError as err:
                msg = f"Failed to perform multi-device register read: {err}"
                raise ReadException(msg) from err
            combined_results.update(chunk_res)

        return combined_results


def create_client(
    transport: AsyncTcpTransport | AsyncRtuTransport,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = DEFAULT_WAIT_AFTER_CONNECT,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
    consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolar instance."""
    # Wrap the transport in a smart transport to add auto-reconnect and cooldown between requests

    smart_transport = TimeoutAwareSmartTransport(
        transport,
        auto_reconnect=RECONNECT_RETRY_STRATEGY,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        response_retry_strategy=RESPONSE_RETRY_STRATEGY,
        retry_on_device_busy=True,
        retry_on_device_failure=True,
        consecutive_timeouts_before_reconnect=consecutive_timeouts_before_reconnect,
    )
    return AsyncHuaweiSolarClient(smart_transport, unit_id=unit_id)


def create_scan_client(
    transport: AsyncTcpTransport | AsyncRtuTransport,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = DEFAULT_WAIT_AFTER_CONNECT,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
    consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient optimized for device scanning.

    Uses no retries so non-responding unit IDs are skipped quickly instead of
    being retried multiple times with backoff.
    """
    smart_transport = TimeoutAwareSmartTransport(
        transport,
        auto_reconnect=RECONNECT_RETRY_STRATEGY,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        response_retry_strategy=SCAN_RESPONSE_RETRY_STRATEGY,
        consecutive_timeouts_before_reconnect=consecutive_timeouts_before_reconnect,
    )
    return AsyncHuaweiSolarClient(smart_transport, unit_id=unit_id)


def create_tcp_client(  # noqa: PLR0913
    host: str,
    port: int = DEFAULT_TCP_PORT,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    timeout: int = DEFAULT_TIMEOUT,
    wait_after_connect: float = DEFAULT_WAIT_AFTER_CONNECT,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
    consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient connected via TCP."""
    transport = AsyncTcpTransport(host, port, timeout=timeout)
    return create_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        consecutive_timeouts_before_reconnect=consecutive_timeouts_before_reconnect,
    )


def create_scan_tcp_client(  # noqa: PLR0913
    host: str,
    port: int = DEFAULT_TCP_PORT,
    *,
    unit_id: int = DEFAULT_UNIT_ID,
    timeout: int = DEFAULT_SCAN_TIMEOUT,
    wait_after_connect: float = DEFAULT_WAIT_AFTER_CONNECT,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
    consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient optimized for TCP device scanning."""
    transport = AsyncTcpTransport(host, port, timeout=timeout)
    return create_scan_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        consecutive_timeouts_before_reconnect=consecutive_timeouts_before_reconnect,
    )


def create_rtu_client(
    port: str,
    *,
    baudrate: int = DEFAULT_BAUDRATE,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = DEFAULT_WAIT_AFTER_CONNECT,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
    consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient connected via RTU."""
    transport = AsyncRtuTransport(port, baudrate=baudrate)
    return create_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        consecutive_timeouts_before_reconnect=consecutive_timeouts_before_reconnect,
    )


def create_scan_rtu_client(
    port: str,
    *,
    baudrate: int = DEFAULT_BAUDRATE,
    unit_id: int = DEFAULT_UNIT_ID,
    wait_after_connect: float = DEFAULT_WAIT_AFTER_CONNECT,
    wait_between_requests: float = DEFAULT_COOLDOWN_TIME,
    consecutive_timeouts_before_reconnect: int = DEFAULT_MAX_CONSECUTIVE_TIMEOUTS,
) -> AsyncHuaweiSolarClient:
    """Create an AsyncHuaweiSolarClient optimized for RTU device scanning."""
    transport = AsyncRtuTransport(port, baudrate=baudrate)
    return create_scan_client(
        transport,
        unit_id=unit_id,
        wait_after_connect=wait_after_connect,
        wait_between_requests=wait_between_requests,
        consecutive_timeouts_before_reconnect=consecutive_timeouts_before_reconnect,
    )
