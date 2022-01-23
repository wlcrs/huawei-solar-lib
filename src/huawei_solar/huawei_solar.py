"""
Get production and status information from the Huawei Inverter using Modbus over TCP
"""
import asyncio
import logging
import backoff
from collections import namedtuple

from .exceptions import HuaweiSolarException
from .registers import REGISTERS, RegisterDefinition

from pymodbus.client.asynchronous.async_io import (
    init_tcp_client,
    ReconnectingAsyncioModbusTcpClient,
    ModbusClientProtocol
)
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException as ModbusConnectionException

LOGGER = logging.getLogger(__name__)

Result = namedtuple("Result", "value unit")


class AsyncHuaweiSolar:
    """Async interface to the Huawei solar inverter"""

    def __init__(self, host, port="502", timeout=5, wait=2, loop=None, slave=0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._wait = wait
        self._slave = slave

        self._client = None

        self.time_zone = None
        self.battery_type = None  # we assume that battery types cannot be mixed
        self.loop = loop

        # use this lock to prevent concurrent requests, as the
        # Huawei inverters can't cope with those
        self._communication_lock = asyncio.Lock()

        # Lock to prevent race condition for creating client
        self._create_client_lock = asyncio.Lock()

    async def _get_client(self) -> ReconnectingAsyncioModbusTcpClient:

        async with self._create_client_lock:
            if self._client is None:
                client = await init_tcp_client(
                    None, self.loop, self._host, self._port, reset_socket=False
                )
                # wait a little bit to prevent a timeout on the first request
                await asyncio.sleep(1)

                # get some registers which are needed to correctly decode
                # all values
                try:
                    self.time_zone = (await self._get("time_zone", client)).value

                    # we assume that when at least one battery is present, it will always be put in storage_unit_1 first
                    self.battery_type = (
                        await self._get("storage_unit_1_product_model", client)
                    ).value

                    self._client = client
                except Exception as err:
                    LOGGER.error(
                        "Encountered an error while doing initial queries. Resetting.",
                        exc_info=err,
                    )
                    # We encountered an error.
                    # Stop and remove the client to properly try again later.
                    try:
                        client.stop()
                    except Exception:
                        pass

        if not self._client:
            raise HuaweiSolarException("Could not initialize the client")

        return self._client

    async def decode_response(
        self, reg: RegisterDefinition, decoder: BinaryPayloadDecoder
    ):
        result = reg.decode(decoder, self)

        if not hasattr(reg, "unit") or callable(reg.unit) or isinstance(reg.unit, dict):
            return Result(result, None)
        return Result(result, reg.unit)

    async def get(self, name):
        return await self._get(name, await self._get_client())

    async def _get(self, name, client):
        """get named register from device"""
        return (await self._get_multiple([name], client))[0]

    async def get_multiple(self, names: list[str]):
        return await self._get_multiple(names, await self._get_client())

    async def _get_multiple(self, names: list[str], client):
        """Read multiple registers at the same time.

        This is only possible if the registers are consecutively available in the
        inverters' memory.
        """

        if len(names) == 0:
            raise ValueError("Expected at least one register name")

        registers = list(map(REGISTERS.get, names))

        if None in registers:
            raise ValueError("Did not recognize all register names")

        for idx in range(1, len(names)):
            if (
                registers[idx - 1].register + registers[idx - 1].length
                > registers[idx].register
            ):
                raise ValueError(
                    "Requested registers must be in monotonically increasing order!"
                )

            register_distance = (
                registers[idx - 1].register
                + registers[idx - 1].length
                - registers[idx].register
            )

            if register_distance > 64:
                raise ValueError(
                    "Gap between requested registers is too large. Split it in two requests"
                )

        total_length = (
            registers[-1].register + registers[-1].length - registers[0].register
        )

        response = await self._read_registers(
            registers[0].register, total_length, client
        )

        decoder = BinaryPayloadDecoder.fromRegisters(
            response.registers, byteorder=Endian.Big, wordorder=Endian.Big
        )

        result = [await self.decode_response(registers[0], decoder)]
        for idx in range(1, len(registers)):
            skip_registers = registers[idx].register - (
                registers[idx - 1].register + registers[idx - 1].length
            )
            decoder.skip_bytes(
                skip_registers * 2
            )  # registers are 16-bit, so we need to multiply by two
            result.append(await self.decode_response(registers[idx], decoder))

        return result

    async def _read_registers(self, register: RegisterDefinition, length: int, client: ReconnectingAsyncioModbusTcpClient):
        """
        Async read register from device.

        The device needs a bit of time between the connection and the first request
        and between requests if there is a long time between them, else it will fail.

        This is solved by sleeping between the first connection and a request,
        and up to 5 retries between following requests.

        It seems to only support connections from one device at the same time.
        """

        def backoff_giveup(details):
            raise ReadException(
                f"Failed to read register {register} after {details['tries']} tries"
            )

        @backoff.on_exception(
            backoff.constant,
            (asyncio.TimeoutError),
            interval=self._wait,
            max_tries=5,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                f"Backing off reading for {details['wait']:0.1f} seconds after {details['tries']} tries"
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_read():

            if (not client.protocol):  # type: ModbusClientProtocol
                message = "failed to connect to device, is the host correct?"
                LOGGER.exception(message)
                raise ConnectionException(message)
            try:
                response = await client.protocol.read_holding_registers(
                    register,
                    length,
                    unit=self._slave,
                    timeout=self._timeout,
                )
                return response

            except ModbusConnectionException:
                message = (
                    "could not read register value, "
                    "is an other device already connected?"
                )
                LOGGER.error(message)
                raise ReadException(message)
            # errors are different with async pymodbus,
            # we should not be able to reach this code. Keep it for debugging
            message = "could not read register value for unknown reason"
            LOGGER.error(message)
            raise ReadException(message)

        async with self._communication_lock:
            LOGGER.debug(f"Reading register {register}")
            return await _do_read()


class ConnectionException(Exception):
    """Exception connecting to device"""


class ReadException(Exception):
    """Exception reading register from device"""
