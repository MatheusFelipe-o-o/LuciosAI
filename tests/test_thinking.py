import unittest
from unittest.mock import patch

from thinking import ThinkingUnavailable, profiles, resolve, chat


class ThinkingTests(unittest.TestCase):
    def test_niveis_nomeados_usam_apenas_valores_anunciados(self):
        self.assertEqual(profiles(("low", "medium", "high", "max")), {
            "light": "low", "medium": "medium", "high": "high",
            "extra_high": "max"})
        self.assertEqual(profiles(("low", "medium", "high")), {
            "light": "low", "medium": "medium", "high": "high"})

    def test_modelo_booleano_tem_apenas_desligado_e_ligado(self):
        self.assertEqual(profiles((False, True)), {"light": False, "high": True})
        with patch("thinking.capabilities", return_value=(False, True)):
            self.assertIs(resolve("qwen", "light"), False)
            self.assertIs(resolve("qwen", "high"), True)
            with self.assertRaises(ThinkingUnavailable):
                resolve("qwen", "medium")
            with self.assertRaises(ThinkingUnavailable):
                resolve("qwen", "extra_high")

    def test_modelo_sem_raciocinio_nao_recebe_nivel_falso(self):
        self.assertEqual(profiles((False,)), {})
        with patch("thinking.capabilities", return_value=(False,)):
            self.assertIsNone(resolve("llama", "auto"))
            with self.assertRaises(ThinkingUnavailable):
                resolve("llama", "high")

    def test_nivel_maximo_modelo_definido_usa_api_nativa(self):
        import io
        import json
        from unittest.mock import Mock
        response = io.BytesIO(b'{"message":{"content":"ok"},"done":true}\n')
        with patch("thinking.urlopen", return_value=response) as opened:
            chunks = list(chat(Mock(), model="modelo", messages=[], think="max", stream=True))
        self.assertEqual(chunks[0]["message"]["content"], "ok")
        request = opened.call_args.args[0]
        self.assertEqual(json.loads(request.data)["think"], "max")
