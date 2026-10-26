"""Offline checks for contract accounting, validation and incomplete coverage."""
from pydantic import ValidationError
from app.collaborations import ContractInput, AssignmentInput, fee_summary, performance, contract_id

base = {'tag':'#롯데마트', 'date':'2026-10-26', 'fee_mode':'bundle', 'fee':300000}
assert ContractInput.model_validate(base).tag == '롯데마트'
assert len(ContractInput.model_validate({**base,'tag':'가'*10}).tag) == 10
for bad in ({**base,'tag':'가'*11}, {**base,'tag':'bad tag'}, {**base,'fee':-1}, {**base,'fee':1.5}, {**base,'date':'bad'}):
    try: ContractInput.model_validate(bad)
    except ValidationError: pass
    else: raise AssertionError('Accepted invalid input')
assert contract_id('Test') == contract_id('test')
posts = {'1':{'fee_override':None}, '2':{'fee_override':50000}}
assert fee_summary({**base,'posts':posts})['agreed'] == 300000
assert fee_summary({**base,'fee_mode':'per_post','fee':100000,'posts':posts})['agreed'] == 150000
assert fee_summary({**base,'fee_mode':'per_post','posts':{}})['agreed'] == 0
assert fee_summary({**base,'posts':posts,'paid_amount':100000})['outstanding'] == 200000
assert fee_summary({**base,'paid_amount':350000})['overpaid'] == 50000
assert fee_summary({**base,'posts':{'1':{'fee_override':0}},'fee_mode':'per_post'})['agreed'] == 0
result = performance({'1','2'}, {'1':{'views':10,'replies':0},'2':{'views':20}}, {'1':{'follows':0}})
assert result['totals']['views'] == 30 and result['totals']['follows'] == 0
assert result['coverage']['follows'] == 1 and result['totals']['reposts'] is None
assert performance(set(),{}, {})['totals']['views'] is None
print('PASS: 10-char tags, bundle counted once, per-post overrides, payments, missing coverage')
