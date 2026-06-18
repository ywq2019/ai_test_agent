"""
WebSocket路由处理
"""
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
import json

from api.websocket_manager import ws_manager
from agent.core import uitest_agent


async def websocket_endpoint(websocket: WebSocket):
    client_id = websocket.query_params.get("client_id", "default")
    await ws_manager.connect(websocket, client_id)

    uitest_agent.set_websocket_manager(ws_manager)

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket连接成功"
        })

        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                message_type = message_data.get("type")

                if message_type == "command":
                    command = message_data.get("message", "")
                    result = await uitest_agent.handle_command(command)
                    await ws_manager.send_personal_message(result, websocket)

                elif message_type == "get_state":
                    state = uitest_agent.get_state()
                    await ws_manager.send_personal_message({
                        "type": "state",
                        "state": state
                    }, websocket)

                elif message_type == "parse_page":
                    url = message_data.get("url")
                    browser = message_data.get("browser", "chromium")
                    if url:
                        elements = await uitest_agent.parse_page(url, browser)
                        await ws_manager.send_personal_message({
                            "type": "page_elements",
                            "elements": elements,
                            "count": len(elements)
                        }, websocket)

                elif message_type == "generate_cases":
                    cases = await uitest_agent.generate_cases()
                    await ws_manager.send_personal_message({
                        "type": "cases_generated",
                        "cases": cases,
                        "count": len(cases)
                    }, websocket)

                elif message_type == "execute":
                    results = await uitest_agent.execute_cases(
                        case_ids=message_data.get("case_ids"),
                        browser_type=message_data.get("browser", "chromium")
                    )
                    await ws_manager.send_personal_message({
                        "type": "execution_completed",
                        "results": results
                    }, websocket)

                elif message_type == "pause":
                    uitest_agent.handle_command("暂停")
                    await ws_manager.send_personal_message({
                        "type": "paused"
                    }, websocket)

                elif message_type == "resume":
                    uitest_agent.handle_command("继续")
                    await ws_manager.send_personal_message({
                        "type": "resumed"
                    }, websocket)

                elif message_type == "stop":
                    uitest_agent.handle_command("停止")
                    await ws_manager.send_personal_message({
                        "type": "stopped"
                    }, websocket)

                else:
                    await ws_manager.send_personal_message({
                        "type": "error",
                        "message": f"Unknown message type: {message_type}"
                    }, websocket)

            except json.JSONDecodeError:
                await ws_manager.send_personal_message({
                    "type": "error",
                    "message": "Invalid JSON format"
                }, websocket)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, client_id)
        logger.info(f"Client {client_id} disconnected")

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket, client_id)
