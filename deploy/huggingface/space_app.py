"""Entry point for a Hugging Face Space on the free tier (Gradio SDK, ZeroGPU).

Gradio runs the web server, as ZeroGPU expects. The screening engine's own API
is attached under /engine, so the PEHCHAAN gateway's PYTHON_API_URL is
https://<space>.hf.space/engine. Every /engine/api call still needs the
x-engine-key header; the engine checks it exactly as it does anywhere else.

The models run on the CPU. ZeroGPU only lends a GPU inside functions marked
@spaces.GPU, and the Space must have at least one: here it is the GPU check on
the Space's page.
"""
import os

os.environ.setdefault("LOCALIZATION_DEVICE", "cpu")
os.environ.setdefault("CLASSIFIER_DEVICE", "cpu")
# Gradio on Spaces normally puts a page-rendering server in front of the app,
# which would answer /engine itself and refuse multipart uploads. Turn it off.
os.environ["GRADIO_SSR_MODE"] = "false"
# Working files (receipts, alerts) go next to the code when that folder is
# writable, otherwise to the temporary folder.
if not os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK):
    os.environ.setdefault("UPLOAD_DIR", "/tmp/pehchaan-uploads")

import spaces  # noqa: E402  (ZeroGPU wants this imported before torch)
import gradio as gr  # noqa: E402
from starlette.routing import Mount  # noqa: E402

from app.main import app as engine  # noqa: E402

PREFIX = "/engine"


class EngineAtPrefix:
    """Passes /engine/... requests to the engine with the prefix removed, so the
    engine sees its usual paths and applies its usual API-key check."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = dict(scope)
            path = scope.get("path", "")
            if path.startswith(PREFIX):
                path = path[len(PREFIX):] or "/"
            scope["path"] = path
            scope["raw_path"] = path.encode()
            scope["root_path"] = ""
        await self.app(scope, receive, send)


@spaces.GPU
def gpu_check() -> str:
    import torch
    if torch.cuda.is_available():
        return f"GPU available: {torch.cuda.get_device_name(0)}"
    return "No GPU available."


with gr.Blocks(title="PEHCHAAN screening engine") as demo:
    gr.Markdown(
        "## PEHCHAAN screening engine\n"
        "This Space hosts the document-screening engine of PEHCHAAN (SIH 2026, PS 26188). "
        "It is called by the PEHCHAAN dashboard, not used directly.\n\n"
        "Open the app: https://tumharipehchaan.vercel.app"
    )
    check = gr.Button("Check the GPU")
    result = gr.Textbox(label="Result", interactive=False)
    check.click(gpu_check, outputs=result)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), ssr_mode=False, prevent_thread_lock=True)
    demo.app.router.routes.insert(0, Mount(PREFIX, app=EngineAtPrefix(engine)))
    demo.block_thread()
