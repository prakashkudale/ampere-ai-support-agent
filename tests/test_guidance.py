from copy import deepcopy
from app.guidance import ACCOUNT_STEPS, select_step
from app.schemas import Route, ChatRequest, DocAnswer
from app.service import SupportService
from test_support import setup, send, seed_docs
import pytest


def use_route(model,monkeypatch,**kwargs):
    monkeypatch.setattr(model,'classify',lambda *args:Route(intent='next_steps',new_issue=False,unresolved=False,**kwargs))


@pytest.mark.parametrize('email,action',[('rahul@example.com','Get a valid API key'),('priya@example.com','Describe the exact symptom'),('sam@example.com','Check that the address')])
@pytest.mark.parametrize('wording',["How can we proceed?","Where do I go from here?","What should I try now?","And then?"])
def test_next_action_policy_across_statuses_and_wordings(setup,monkeypatch,email,action,wording):
    service,model,store,_=setup
    first=send(service,'My agent is broken: '+email)
    use_route(model,monkeypatch)
    result=send(service,wording,'r2')
    assert action in result.answer and result.answer!=first.answer
    assert len(model.lookups)==1 and store.state('c1')['rounds']==0


def test_completed_step_advances_without_marking_issue_resolved(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    send(service,'What next?','r2')
    use_route(model,monkeypatch,followup='completed',step_number=1)
    result=send(service,'I have the key now','r3')
    assert 'step 2' in result.answer
    s=store.state('c1');assert s['guidance']['completed']==[0] and s['issue_id']


def test_named_later_action_does_not_send_user_back_to_earlier_steps(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    use_route(model,monkeypatch,followup='completed',step_number=2)
    result=send(service,'I already added the key','r2')
    assert 'step 3' in result.answer
    assert store.state('c1')['guidance']['completed']==[1]


def test_clarification_preserves_progress_and_does_not_count_as_failure(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    send(service,'What next?','r2')
    before=deepcopy(store.state('c1')['guidance'])
    use_route(model,monkeypatch,followup='clarify')
    result=send(service,'Explain that part please','r3')
    assert result.outcome=='needs_clarification'
    assert store.state('c1')['guidance']==before and store.state('c1')['rounds']==0


def test_failure_does_not_advance_and_second_failure_escalates(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    send(service,'What next?','r2')
    use_route(model,monkeypatch,followup='failed')
    assert send(service,'This step failed','r3').outcome=='needs_clarification'
    assert store.state('c1')['guidance']['completed']==[]
    assert send(service,'Still fails after checking','r4').outcome=='escalated'


@pytest.mark.parametrize('failed',[False,True])
def test_ticket_next_steps_never_retry_or_duplicate_delivery(setup,failed):
    service,model,store,settings=setup
    settings.mock_discord_result='failure' if failed else 'success'
    first=send(service,'I need a human')
    result=send(service,'What next?','r2')
    assert result.ticket_id==first.ticket_id
    assert store.latest_ticket('c1')['attempts']==1
    assert ('retry delivery' if failed else 'simulated handoff is complete') in result.answer


def test_doc_progress_keeps_sources_and_uses_latest_topic(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    seed_docs(store);model.intent='docs'
    model.doc_answer=DocAnswer(answer='1. Create your bot.\n2. Test dashboard chat.\n3. Connect a channel.',source_ids=[1],supported=True)
    send(service,'How do I create a bot?','r2')
    use_route(model,monkeypatch,followup='completed',step_number=1)
    result=send(service,'I completed the first step','r3')
    assert 'Test dashboard chat' in result.answer and result.sources
    assert 'API key' not in result.answer and len(model.lookups)==1


def test_only_explicit_final_confirmation_resolves_account(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    use_route(model,monkeypatch,followup='completed',step_number=3)
    result=send(service,'I ran the last test','r2')
    assert result.outcome=='needs_clarification' and store.state('c1')['issue_id']
    send(service,'yes','r3')
    assert store.state('c1')['issue_id'] is None


def test_undefined_step_never_indexes_or_changes_plan(setup,monkeypatch):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    before=deepcopy(store.state('c1')['guidance'])
    use_route(model,monkeypatch,step_number=29)
    assert send(service,'Explain step 29','r2').outcome=='needs_clarification'
    assert store.state('c1')['guidance']==before


def test_progress_survives_restart_and_acknowledgements(setup,monkeypatch):
    service,model,store,settings=setup
    send(service,'My agent is broken: rahul@example.com')
    use_route(model,monkeypatch,followup='completed',step_number=1)
    send(service,'I completed the first step','r2')
    send(service,'thanks','r3')
    restarted=SupportService(store,model,settings)
    use_route(model,monkeypatch,followup='clarify',step_number=2)
    result=send(restarted,'Can you explain that step?','r4')
    assert 'step 2' in result.answer.lower() and store.state('c1')['guidance']['completed']==[0]


def test_focused_interpretation_overrides_topic_router_default(setup,monkeypatch):
    from app.schemas import ProgressDecision
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    use_route(model,monkeypatch,followup='advance')
    monkeypatch.setattr(model,'interpret_followup',lambda *args:ProgressDecision(action='completed',step_number=1),raising=False)
    result=send(service,'I have already got the key','r2')
    assert 'step 2' in result.answer and store.state('c1')['guidance']['completed']==[0]


def test_pricing_list_does_not_become_an_instruction_plan(setup):
    from app.guidance import document_plan
    service,model,store,_=setup
    state=store.state('c1')
    document_plan(state,'1. Free is $0.\n2. Pro is $39.',[],'What does Ampere cost?')
    store.save_state('c1',state)
    assert send(service,'What next?').outcome=='needs_clarification'


def test_new_unsupported_doc_topic_does_not_revive_old_account_plan(setup):
    service,model,store,_=setup
    send(service,'My agent is broken: rahul@example.com')
    model.intent='docs'
    send(service,'Does Ampere have an unknown teleport feature?','r2')
    result=send(service,'What next?','r3')
    assert 'API key' not in result.answer
