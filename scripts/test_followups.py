"""Real-model semantic follow-up acceptance cases; isolated demo data, billable."""
import json
from pathlib import Path
import sys
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.model import ClaudeModel
from app.schemas import ChatRequest
from app.service import SupportService
from app.storage import Store

CASES={
 'offline-progress':[
  ('My assistant is broken: rahul@example.com',{}),
  ('Where do I go from here?',{'step':0,'rounds':0}),
  ("I've got a valid provider key now",{'step':1,'completed':[0]}),
  ("I've added that key to the assistant configuration",{'step':2,'completed':[0,1]}),
  ('Can you explain what that step means?',{'step':2,'rounds':0}),
  ('I tried that test and it still fails',{'step':2,'rounds':1}),
 ],
 'running-progress':[
  ('My assistant is broken: priya@example.com',{}),
  ('What should I try now?',{'step':0,'rounds':0}),
  ('Walk me through that instruction please',{'step':0,'rounds':0}),
 ],
 'unknown-account':[
  ('My assistant is broken: sam@example.com',{}),
  ('How can we proceed?',{'step':0,'rounds':0}),
  ('I checked and that is definitely the registered address. What is the next step?',{'contains':'human','lookups':1}),
 ],
 'docs-progress':[
  ('How do I set up a scheduled reminder?',{'sources':True}),
  ('I already described the job in chat. What comes after that?',{'step':1,'sources':True}),
  ('Explain this step more simply please',{'step':1,'sources':True}),
  ('I reviewed the job in the dashboard. What is next?',{'step':2,'sources':True}),
 ],
 'pending-ticket':[
  ('I need a human',{'outcome':'escalation_pending'}),
  ('Where do we go from here?',{'outcome':'escalation_pending','contains':'retry','attempts':1}),
 ],
 'delivered-ticket':[
  ('I need a human',{'outcome':'escalated'}),
  ('Is there anything else I need to do now?',{'outcome':'escalated','contains':'simulated','attempts':1}),
 ],
 'no-task':[
  ('How do I proceed?',{'outcome':'needs_clarification'}),
 ],
}


class Traced(ClaudeModel):
 def __init__(self,s):super().__init__(s);self.lookups=0;self.events=[]
 def validate_lookup(self,email):self.lookups+=1;return super().validate_lookup(email)
 def classify(self,*args):
  r=super().classify(*args);self.events.append(r.model_dump());return r


def main():
 settings=Settings.load().model_copy(update={'database_path':'.tmp/followups.db'})
 original=Store(Settings.load().database_path);store=Store(settings.database_path)
 with original.connect() as db:passages=[tuple(r) for r in db.execute('SELECT url,title,text FROM passages')]
 with store.connect() as db:
  db.execute('DELETE FROM passages');db.executemany('INSERT INTO passages(url,title,text) VALUES(?,?,?)',passages)
  db.execute("INSERT INTO passage_search(passage_search) VALUES('rebuild')")
 results=[];run=uuid4().hex
 for name,turns in CASES.items():
  settings.mock_discord_result='failure' if name=='pending-ticket' else 'success'
  model=Traced(settings);service=SupportService(store,model,settings);chat=run+'-'+name
  for index,(message,check) in enumerate(turns):
   failures=[];answer='';before=len(model.events)
   try:
    r=service.chat(ChatRequest(conversation_id=chat,request_id=f'r{index}',message=message));answer=r.answer
    state=store.state(chat);plan=state.get('guidance') or {}
    for key,field in [('step','presented'),('completed','completed')]:
     if key in check and plan.get(field)!=check[key]:failures.append(key)
    if 'rounds' in check and state['rounds']!=check['rounds']:failures.append('rounds')
    if 'sources' in check and bool(r.sources)!=check['sources']:failures.append('sources')
    if 'contains' in check and check['contains'] not in answer.lower():failures.append('content')
    if 'outcome' in check and r.outcome!=check['outcome']:failures.append('outcome:'+r.outcome)
    if 'lookups' in check and model.lookups!=check['lookups']:failures.append('lookup count')
    if 'attempts' in check and store.latest_ticket(chat)['attempts']!=check['attempts']:failures.append('delivery count')
   except Exception as exc:failures.append(type(exc).__name__)
   row={'case':name,'turn':index+1,'message':message,'answer':answer,'routes':model.events[before:],'failures':failures}
   results.append(row);print(json.dumps({k:row[k] for k in ('case','turn','failures')}),flush=True)
 Path('.tmp/followup-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 print('FOLLOWUPS:',sum(not r['failures'] for r in results),'/',len(results),flush=True)
 return int(any(r['failures'] for r in results))

if __name__=='__main__':sys.exit(main())
