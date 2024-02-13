import asyncio
import struct
from enum import IntEnum

import msgpack
from loguru import logger


class TCP(IntEnum):
    COM = 0  # COMMUNICATION (ACCEPTED, CLOSED, REFUSED)
    AGL = 1  # AGENT LIST
    MAP = 2  # MAP: NAME, CHANGES, etc.
    TIME = 3  # TIME: LEFT TIME
    ERR = 4  # ERROR


class Msg(IntEnum):
    TYPE = 501
    BODY = 502
    WELCOME = 503
    READY = 504
    QUIT = 505
    ACCEPT = 506
    AGENTS = 1001
    PACKS = 1002
    CONTENT_NAME = 1003
    CONTENT_TYPE = 1004
    CONTENT_TEAM = 1005
    CONTENT_HEALTH = 1006
    CONTENT_AMMO = 1007
    CONTENT_POSITION = 1008
    CONTENT_VELOCITY = 1009
    CONTENT_HEADING = 1010
    CONTENT_CARRYINGFLAG = 1011


class Server(object):
    def __init__(self, map_name, port=8001):
        self.clients = {}
        self.map_name = map_name
        self.port = port
        self.server = None

    def get_connections(self):
        return self.clients.keys()

    async def start(self):
        self.server = await asyncio.start_server(self.accept_client, "", self.port)
        logger.info("Render Server started: {}".format(self.server))

    async def stop(self):
        await self.server.stop()
        await self.server.wait_closed()

    def accept_client(self, client_reader, client_writer):
        logger.info("New render connection")
        task = asyncio.Task(self.handle_client(client_reader, client_writer))
        self.clients[task] = (client_reader, client_writer, False)

        def client_done(task_):
            del self.clients[task_]
            client_writer.close()
            logger.info("End Connection")

        task.add_done_callback(client_done)

    def is_ready(self, task):
        return self.clients[task][2]

    async def handle_client(self, reader, writer):
        task = None
        for k, v in self.clients.items():
            if v[0] == reader and v[1] == writer:
                task = k
                break
        # + ":" + str(self.request)
        logger.info("Preparing Connection to " + str(task))

        try:
            self.send_msg_to_render_engine(task, msg_type=TCP.COM, msg=Msg.WELCOME)
            await writer.drain()
            logger.info("pygomas render engine server v. 0.2.0")
        except Exception as e:
            logger.error("EXCEPTION IN WELCOME MESSAGE")
            logger.error(str(e))

        while True:
            size_of_msg = await reader.read(4)
            if not size_of_msg:
                continue
            size_of_msg = struct.unpack(">I", size_of_msg)[0]
            logger.debug("Got size " + str(size_of_msg))

            data = bytes()
            while len(data) < size_of_msg:
                packet = await reader.read(size_of_msg - len(data))
                if not packet:
                    break
                data += packet

            if len(data) == 0:
                logger.info("Received no data")
                # exit loop and disconnect
                return

            data = msgpack.unpackb(data, raw=False, strict_map_key=False)

            logger.info("Client says:" + str(data))
            if data[Msg.TYPE] == TCP.COM:
                if data[Msg.BODY] == Msg.READY:
                    logger.info("Server: Connection Accepted")
                    self.send_msg_to_render_engine(task, TCP.COM, Msg.ACCEPT)
                    self.send_msg_to_render_engine(task, TCP.MAP, self.map_name)
                    logger.info("Sending: NAME: " + self.map_name)

                    self.clients[task] = (reader, writer, True)

                elif data[Msg.BODY] == Msg.QUIT:
                    logger.info("Server: Client quitted")
                    self.send_msg_to_render_engine(
                        task, TCP.COM, "Server: Connection Closed"
                    )
                    return
                else:
                    # Close connection
                    logger.info("Socket closed, closing connection.")
                    return

            elif data[Msg.TYPE] == TCP.MAP:
                logger.info("Server: Client requested mapname")
                self.send_msg_to_render_engine(task, TCP.MAP, self.map_name)
                self.clients[task] = (reader, writer, True)

    def send_msg_to_render_engine(self, task, msg_type, msg):
        writer = None
        for k, v in self.clients.items():
            if k == task:
                writer = v[1]
                break
        if writer is None:
            logger.info("Connection for {task} not found".format(task=task))
            return

        msg_to_send = msgpack.packb(
            {Msg.TYPE: msg_type, Msg.BODY: msg}, use_bin_type=True
        )
        size_of_package = len(msg_to_send)

        try:
            msg = struct.pack(">I", size_of_package) + msg_to_send
            writer.write(msg)
        except Exception as e:
            logger.error("EXCEPTION IN SENDMSGTORE: {}".format(e))
