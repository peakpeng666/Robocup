"""booster_interface.srv -- RpcService (request/response each wrap one Booster API message)."""
from booster_interface.msg import BoosterApiReqMsg, BoosterApiRespMsg


class RpcService:
    class Request:
        __slots__ = ("msg",)

        def __init__(self):
            self.msg = BoosterApiReqMsg()

    class Response:
        __slots__ = ("msg",)

        def __init__(self):
            self.msg = BoosterApiRespMsg()
