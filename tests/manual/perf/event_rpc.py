from airdc.common.utils.event_rpc import (
    ProcessEventRpcArgs,
    EventRpcClient,
    EventRpcServer,
)
from multiprocessing.context import SpawnProcess
import time


def server(event_rpc_args: ProcessEventRpcArgs):
    server = EventRpcServer(event_rpc_args)
    print("Server started")
    while server.wait():
        print("Server received request")
        server.respond()
    print("Server exited")


def main(num_tests=10):
    event_rpc_args = ProcessEventRpcArgs()
    p = SpawnProcess(target=server, args=(event_rpc_args,))
    p.start()
    time.sleep(1)  # wait for the server to start
    event_rpc_client = EventRpcClient(event_rpc_args)
    for _ in range(num_tests):
        start = time.perf_counter()
        event_rpc_client.request()
        print(f"RPC time cost: {(time.perf_counter() - start) * 1000:.3f} ms")
        time.sleep(0.5)
    event_rpc_client.shutdown()
    p.join()


if __name__ == "__main__":
    main()
