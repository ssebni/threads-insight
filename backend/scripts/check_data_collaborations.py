"""Offline checks: specified date/value/memo endpoints drive collaboration CRUD."""
from datetime import datetime,timezone
from unittest.mock import patch
from pydantic import ValidationError
from app.data_api import DataInput,create_data,update_data,delete_data,summary_for,list_data
from app.collaborations import assign_post,AssignmentInput

class Snapshot:
    def __init__(self,ref):self.reference=ref;self.id=ref.path.split('/')[-1];self.exists=ref.path in ref.db.rows
    def to_dict(self):return dict(self.reference.db.rows[self.reference.path]) if self.exists else None
class Ref:
    def __init__(self,db,path):self.db=db;self.path=path
    def get(self,**kwargs):return Snapshot(self)
class Collection:
    def __init__(self,db,name):self.db=db;self.name=name;self.filter=None;self.maximum=10000
    def document(self,identity):return Ref(self.db,self.name+'/'+identity)
    def limit(self,value):self.maximum=value;return self
    def where(self,filter):self.filter=filter;return self
    def stream(self,**kwargs):
        rows=[Snapshot(Ref(self.db,path)) for path in self.db.rows if path.startswith(self.name+'/')]
        if self.filter:rows=[row for row in rows if row.to_dict().get(self.filter.field_path)==self.filter.value]
        return rows[:self.maximum]
class Transaction:
    def __init__(self,db):self.db=db
    def set(self,ref,value):self.db.rows[ref.path]=dict(value)
    def delete(self,ref):self.db.rows.pop(ref.path,None)
class DB:
    def __init__(self):self.rows={}
    def collection(self,name):return Collection(self,name)
    def transaction(self):return Transaction(self)

db=DB();db.rows['threads_posts/123']={'timestamp':datetime.now(timezone.utc),'text':'original'}
db.rows['data/threads_123']={'date':'2026-10-26','value':1000,'metric':'views','source':'threads'}
body=DataInput.model_validate({'date':'2026-10-26','value':300000,'memo':'협업 메모','collaboration':{'tag':'검증협업','fee_mode':'bundle','paid_amount':50000}})
with patch('app.collaborations.firestore.transactional',lambda fn:fn):
    created=create_data(body,db); identity=created['contract_id'];record_id=created['id']
    assert created['date']=='2026-10-26' and created['value']==300000 and created['memo']=='협업 메모'
    assert created['unit']=='KRW'
    assign_post(identity,'123',AssignmentInput(assigned=True),db)
    assert db.rows['data/'+record_id]['value']==300000  # Bundle stays one fee.
    changed=body.model_copy(update={'value':100000.0})
    changed.collaboration=body.collaboration.model_copy(update={'fee_mode':'per_post'})
    assert update_data(record_id,changed,db)['value']==100000
    assign_post(identity,'123',AssignmentInput(assigned=True,fee_override=75000),db)
    assert db.rows['data/'+record_id]['value']==75000
    summary=summary_for(db)
    assert summary['metrics']['total']==1000 and summary['count']==1
    assert summary['collaboration_revenue']['agreed_total']==75000
    assert list_data(limit=100,cursor=None,kind='collaboration',db=db)['items'][0]['id']==record_id
    delete_data(record_id,db)
    assert 'collaborations/'+identity not in db.rows and 'data/'+record_id not in db.rows
    assert db.rows['threads_posts/123']['text']=='original'
try:DataInput.model_validate({**body.model_dump(mode='json'),'value':1.5})
except ValidationError:pass
else:raise AssertionError('Fractional won accepted')
print('PASS: specified data CRUD, transactional mirror, assignments, currency/view separation, original protection')
