import asyncio
import json
from datetime import datetime, timedelta

from spade.behaviour import TimeoutBehaviour
from spade.message import Message

from pygomas.ontology import Action, Performative, Belief
from .pack import Pack, PACK_MEDICPACK, PACK_AUTODESTROY_TIMEOUT

now = datetime.now


class MedicPack(Pack):
    async def setup(self):
        self.type = PACK_MEDICPACK
        timeout = now() + timedelta(seconds=PACK_AUTODESTROY_TIMEOUT)
        self.add_behaviour(self.AutoDestroyBehaviour(start_at=timeout))
        await super().setup()

    async def perform_pack_taken(self, content):
        await self.stop()

    class AutoDestroyBehaviour(TimeoutBehaviour):
        async def run(self):
            msg = Message(to=self.agent.manager)
            msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.INFORM))
            content = {Belief.NAME: self.agent.name, Action.ACTION: Action.DESTROY}
            msg.body = json.dumps(content)
            if self.agent.is_alive():
                await self.send(msg)
            await asyncio.sleep(1)
            await self.agent.stop()
