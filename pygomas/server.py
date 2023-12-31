import asyncio
import struct

import msgpack

from loguru import logger

TCP_COM = 0  # COMMUNICATION (ACCEPTED, CLOSED, REFUSED)
TCP_AGL = 1  # AGENT LIST
TCP_MAP = 2  # MAP: NAME, CHANGES, etc.
TCP_TIME = 3  # TIME: LEFT TIME
TCP_ERR = 4  # ERROR

MSG_TYPE = 501
MSG_BODY = 502
WELCOME_MSG = 503
READY_MSG = 504
QUIT_MSG = 505
ACCEPT_MSG = 506

MSG_AGENTS = 1001
MSG_PACKS = 1002
MSG_CONTENT_NAME = 1003
MSG_CONTENT_TYPE = 1004
MSG_CONTENT_TEAM = 1005
MSG_CONTENT_HEALTH = 1006
MSG_CONTENT_AMMO = 1007
MSG_CONTENT_POSITION = 1008
MSG_CONTENT_VELOCITY = 1009
MSG_CONTENT_HEADING = 1010
MSG_CONTENT_CARRYINGFLAG = 1011


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
            self.send_msg_to_render_engine(task, msg_type=TCP_COM, msg=WELCOME_MSG)
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
            if data[MSG_TYPE] == TCP_COM:
                if data[MSG_BODY] == READY_MSG:
                    logger.info("Server: Connection Accepted")
                    self.send_msg_to_render_engine(task, TCP_COM, ACCEPT_MSG)
                    self.send_msg_to_render_engine(task, TCP_MAP, self.map_name)
                    logger.info("Sending: NAME: " + self.map_name)

                    self.clients[task] = (reader, writer, True)

                elif data[MSG_BODY] == QUIT_MSG:
                    logger.info("Server: Client quitted")
                    self.send_msg_to_render_engine(
                        task, TCP_COM, "Server: Connection Closed"
                    )
                    return
                else:
                    # Close connection
                    logger.info("Socket closed, closing connection.")
                    return

            elif data[MSG_TYPE] == TCP_MAP:
                logger.info("Server: Client requested mapname")
                self.send_msg_to_render_engine(task, TCP_MAP, self.map_name)
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
            {MSG_TYPE: msg_type, MSG_BODY: msg}, use_bin_type=True
        )
        size_of_package = len(msg_to_send)

        try:
            msg = struct.pack(">I", size_of_package) + msg_to_send
            writer.write(msg)
        except Exception as e:
            logger.error("EXCEPTION IN SENDMSGTORE: {}".format(e))
