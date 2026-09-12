import asyncio

from app.runtime.guided_workflow import GuidedBrowserWorkflow, WorkflowStore


def test_guided_email_clarifies_executes_confirms_and_learns(tmp_path):
    responses = [
        '{"summary":"send leave email","questions":["Which two dates?"],"steps":[]}',
        '{"summary":"send leave email","questions":[],"steps":['
        '{"action":"navigate","url":"https://mail.google.com/"},'
        '{"action":"fill","target":"To","value":"person@example.com"},'
        '{"action":"click","target":"Send","external_effect":true}]}'
    ]
    class Provider:
        async def open(self): pass
        async def verify_page(self): pass
        async def start_conversation(self): pass
        async def send_prompt(self, _): pass
        async def wait_for_response(self): pass
        async def extract_response(self): return responses.pop(0)
    class Locator:
        async def count(self): return 1
        async def fill(self, value): actions.append(("fill", value))
        async def click(self): actions.append(("click", "Send"))
        @property
        def first(self): return self
    class Page:
        def get_by_label(self, *_args, **_kwargs): return Locator()
        def get_by_role(self, *_args, **_kwargs): return Locator()
        def get_by_text(self, *_args, **_kwargs): return Locator()
    class Browser:
        async def start(self): actions.append(("start", ""))
        async def page_for(self, url): actions.append(("navigate", url)); return Page()
    class Prompt:
        def ask(self, _): return "September 14 and 15"
        def confirm(self, _): return True
    actions = []
    store = WorkflowStore(tmp_path / "workflows.json")
    result = asyncio.run(GuidedBrowserWorkflow(Provider(), Browser(), store, Prompt()).run("send email"))
    assert result.startswith("Completed")
    assert actions == [("start", ""), ("navigate", "https://mail.google.com/"),
                       ("fill", "person@example.com"), ("click", "Send")]
    saved = store.recent()
    assert saved[0]["steps"][1]["target"] == "To"
    assert "person@example.com" not in store.path.read_text()


def test_guided_workflow_rejects_unsafe_plan_and_requires_approval(tmp_path):
    unsafe = '{"summary":"bad","questions":[],"steps":[{"action":"shell","target":"x"}]}'
    try:
        GuidedBrowserWorkflow.parse(unsafe)
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unsafe action was accepted")
    assert GuidedBrowserWorkflow.supports("Please send an email")
