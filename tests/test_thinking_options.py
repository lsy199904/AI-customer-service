"""Provider thinking options must use the selected wire format without changing old defaults."""
import unittest
from unittest.mock import patch
from app.core import thinking_options,Settings

class ThinkingOptionsTests(unittest.TestCase):
    def test_legacy_default(self):
        with patch.dict('os.environ',{},clear=True):
            self.assertEqual(thinking_options('Qwen/Qwen3-32B'),{'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}})
            self.assertEqual(thinking_options('another-model'),{})

    def test_siliconflow_top_level(self):
        with patch.dict('os.environ',{'MODEL_THINKING_FORMAT':'enable_thinking','MODEL_DISABLE_THINKING':'true'}):
            self.assertEqual(thinking_options('Qwen/Qwen3-32B'),{'extra_body':{'enable_thinking':False}})

    def test_disabled_or_unsupported_does_not_send_parameters(self):
        for config in ({'MODEL_THINKING_FORMAT':'none','MODEL_DISABLE_THINKING':'true'},
                       {'MODEL_THINKING_FORMAT':'enable_thinking','MODEL_DISABLE_THINKING':'false'}):
            with patch.dict('os.environ',config):self.assertEqual(thinking_options('Qwen/Qwen3-32B'),{})

    def test_invalid_format_fails_before_request(self):
        with patch.dict('os.environ',{'MODEL_THINKING_FORMAT':'typo'}):
            with self.assertRaises(ValueError):thinking_options('Qwen/Qwen3-32B')
            with self.assertRaises(ValueError):Settings(secret='x'*40).validate()

if __name__=='__main__':unittest.main()
