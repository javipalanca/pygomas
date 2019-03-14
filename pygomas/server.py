import asyncio
import time

from loguru import logger

from spade.container import Container

SERVER_PORT = 8001 #8072  # our server's own port

TCP_COM = 0  # COMMUNICATION (ACCEPTED, CLOSED, REFUSED)
TCP_AGL = 1  # AGENT LIST
TCP_MAP = 2  # MAP: NAME, CHANGES, etc.
TCP_TIME = 3  # TIME: LEFT TIME


class Server(object):
    def __init__(self, map_name):
        self.clients = {}
        self.map_name = map_name
        self.server = None

        self.container = Container()

        self.loop = self.container.loop

        self.coro = asyncio.start_server(self.accept_client, "", SERVER_PORT, loop=self.loop)

    def get_connections(self):
        return self.clients.keys()

    def start(self):
        self.server = self.loop.create_task(self.coro)
        logger.info("Render Server started: {}".format(self.server))

    def stop(self):
        self.server.stop()
        self.loop.run_until_complete(self.server.wait_closed())

    def accept_client(self, client_reader, client_writer):
        logger.info("New Connection")
        task = asyncio.Task(self.handle_client(client_reader, client_writer))
        self.clients[task] = (client_reader, client_writer)

        def client_done(task_):
            del self.clients[task_]
            client_writer.close()
            logger.info("End Connection")

        task.add_done_callback(client_done)

    async def handle_client(self, reader, writer):
        task = None
        for k, v in self.clients.items():
            if v == (reader, writer):
                task = k
                break
        logger.info("Preparing Connection to " + str(task))  # + ":" + str(self.request)

        try:
            writer.write("JGOMAS Render Engine Server v. 0.1.0, {}\n".format(time.asctime()).encode())
            logger.info("JGOMAS Render Engine Server v. 0.1.0")
            # self.wfile.flush()
        except Exception as e:
            logger.info(str(e))

        while True:
            # data = await asyncio.wait_for(reader.readline(), timeout=10.0)
            data = await reader.readline()
            if data is None:
                logger.info("Received no data")
                # exit echo loop and disconnect
                return
            # self.synchronizer.release()
            data = data.decode().rstrip()
            logger.info("Client says:" + data)
            if "READY" in data:
                logger.info("Server: Connection Accepted")
                self.send_msg_to_render_engine(task, TCP_COM, "Server: Connection Accepted ")
                logger.info("Sending: NAME: " + self.map_name)
                self.send_msg_to_render_engine(task, TCP_MAP, "NAME: " + self.map_name + "  ")

            elif "MAPNAME" in data:
                logger.info("Server: Client requested mapname")
                self.send_msg_to_render_engine(task, TCP_MAP, "NAME: " + self.map_name + "  ")

            elif "QUIT" in data:
                logger.info("Server: Client quitted")
                self.send_msg_to_render_engine(task, TCP_COM, "Server: Connection Closed")
                return
            else:
                # Close connection
                logger.info("Socket closed, closing connection.")
                return

    def send_msg_to_render_engine(self, task, msg_type, msg):
        writer = None
        for k, v in self.clients.items():
            if k == task:
                writer = v[1]
                break
        if writer is None:
            logger.info("Connection for {task} not found".format(task=task))
            return
        type_dict = {TCP_COM: "COM", TCP_AGL: "AGL", TCP_MAP: "MAP", TCP_TIME: "TIME"}

        msg_type = type_dict[msg_type] if msg_type in type_dict else "ERR"

        msg_to_send = "{} {}\n".format(msg_type, msg)

        try:
            writer.write(msg_to_send.encode())
        except:
            logger.error("EXCEPTION IN SENDMSGTORE")