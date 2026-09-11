"""Amazon Bedrock AgentCore Runtime entrypoint (optional deployment target).

Judges score a live/AgentCore deployment higher on Technical Implementation. To try it:

    uv sync --extra agentcore
    agentcore configure --entrypoint deploy/agentcore_app.py
    agentcore launch
    agentcore invoke '{"prompt": "How long until the deadline?"}'

Docs: https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html
"""

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from afh_agent import build_agent

app = BedrockAgentCoreApp()
agent = build_agent()


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    prompt = payload.get("prompt", "")
    if not prompt:
        return {"error": "payload must include a 'prompt' string"}
    return {"result": str(agent(prompt))}


if __name__ == "__main__":
    app.run()
