"""Offline regression checks for recall scope, reuse, and provider context."""
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from app.chat_memory import clear_answer_memory, context_key, normalize_question, recall, reference, saved_pairs
from app.chat import ChatInput, chat, generate_reply, requests_at

QUESTION='조회수 10만 이상 나온 게시물 공통점이 뭐야?'
NOW=datetime.now(timezone.utc)

def pair(question=QUESTION, identity='saved1', previous=None):
    return {'question':question,'answer':'저장된 실제 답변','key':normalize_question(question),
            'conversation_id':identity,'message_index':1,'saved_at':NOW,
            'context':context_key(previous or [])}


class MemoryChecks(unittest.TestCase):
    def tearDown(self):
        clear_answer_memory();requests_at.clear()

    def test_normalization_and_newest_match(self):
        with patch('app.chat_memory.saved_pairs',return_value=[pair(identity='newest'),pair(identity='older')]):
            exact,similar=recall(Mock(),'  조회수  10만 이상 나온 게시물 공통점이 뭐야!!! ',[])
        self.assertEqual(exact['conversation_id'],'newest');self.assertEqual(similar,[])

    def test_similar_question_uses_reference(self):
        with patch('app.chat_memory.saved_pairs',return_value=[pair()]):
            exact,similar=recall(Mock(),'조회수 10만 이상 나온 게시글 공통점 알려줘',[])
        self.assertIsNone(exact);self.assertEqual(len(similar),1)

    def test_different_threshold_operator_or_metric_not_referenced(self):
        for question in ['조회수 5만 이상 나온 게시물 공통점이 뭐야?',
                         '조회수 10만 이하 나온 게시물 공통점이 뭐야?',
                         '좋아요 10만 이상 나온 게시물 공통점이 뭐야?']:
            with patch('app.chat_memory.saved_pairs',return_value=[pair()]):
                self.assertEqual(recall(Mock(),question,[]),(None,[]))

    def test_contextual_followup_does_not_cross_conversations(self):
        question='그 게시물의 공통점은?';previous=[{'role':'user','content':QUESTION}]
        with patch('app.chat_memory.saved_pairs',return_value=[pair(question,previous=previous)]):
            self.assertEqual(recall(Mock(),question,previous,'another'),(None,[]))
            self.assertIsNotNone(recall(Mock(),question,previous,'saved1')[0])
            self.assertEqual(recall(Mock(),question,[],None),(None,[]))

    def test_history_cache_and_invalidation(self):
        db=Mock();stream=db.collection.return_value.order_by.return_value.limit.return_value.stream
        stream.return_value=[Mock(id='saved1',to_dict=lambda:{'updated_at':NOW,'messages':[
            {'role':'user','content':QUESTION},{'role':'assistant','content':'old'}]})]
        self.assertEqual(len(saved_pairs(db)),1);saved_pairs(db)
        self.assertEqual(stream.call_count,1)
        clear_answer_memory();stream.return_value=[]
        self.assertEqual(saved_pairs(db),[]);self.assertEqual(stream.call_count,2)

    def test_exact_reuse_never_calls_model_or_writes_duplicate(self):
        db=Mock()
        with patch('app.chat.recall',return_value=(pair(),[])), \
             patch('app.chat.generate_reply') as model, patch('app.chat.summary_for') as summary:
            result=chat(ChatInput(message=QUESTION),db)
        self.assertTrue(result['reused']);self.assertEqual(result['answer'],'저장된 실제 답변')
        model.assert_not_called();summary.assert_not_called();db.collection.assert_not_called()

    def test_similar_reference_is_injected_and_new_answer_saved(self):
        db=Mock();db.collection.return_value.document.return_value.id='new1'
        with patch('app.chat.recall',return_value=(None,[pair()])), \
             patch('app.chat.generate_reply',return_value='최신 근거로 답변') as model, \
             patch('app.chat.summary_for',return_value={'count':120}), \
             patch('app.chat.post_evidence',return_value={'index':[]}):
            result=chat(ChatInput(message='조회수 10만 이상 게시글 공통점 알려줘'),db)
        self.assertFalse(result['reused'])
        self.assertEqual(model.call_args.args[1]['previous_answers'][0]['answer'],'저장된 실제 답변')
        saved=db.collection.return_value.document.return_value.create.call_args.args[0]
        self.assertEqual(saved['messages'][-1]['answer_origin']['references'][0]['conversation_id'],'saved1')

    def test_dated_reference_and_ui_metadata_fit_provider_protocol(self):
        summary={'count':120,'previous_answers':[{**reference(pair()),'answer':'과거 답변'}]}
        messages=[{'role':'assistant','content':'이전 메시지','answered_at':NOW,'answer_origin':{}},
                  {'role':'user','content':QUESTION}]
        with patch('app.chat.chat_status',return_value={'provider':'codyssey_anthropic'}), \
             patch('app.chat.codyssey_reply',return_value='답변') as model:
            generate_reply(messages,summary)
        self.assertEqual(set(model.call_args.args[0][0]),{'role','content'})
        self.assertIn(NOW.isoformat(),model.call_args.args[1])


if __name__=='__main__':unittest.main()
