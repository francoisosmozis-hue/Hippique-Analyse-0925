from fastapi import FastAPI


def create_app(agent):
    app = FastAPI()

    @app.post("/run")
    async def run(payload: dict):
        return await agent.execute(payload)

    return app
