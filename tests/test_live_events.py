from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest

from benchmark import executar_benchmark
from orchestrator import Configuracao, medir_etapa, observar_medicoes


class LiveEventsTests(unittest.TestCase):
    def test_eventos_aninhados_e_falhas(self):
        eventos = []
        with observar_medicoes(eventos.append):
            with medir_etapa([], "pai"):
                with medir_etapa([], "filho"):
                    pass
        self.assertEqual([(e["fase"], e["etapa"]) for e in eventos], [
            ("inicio", "pai"), ("inicio", "pai/filho"),
            ("fim", "pai/filho"), ("fim", "pai"),
        ])
        self.assertTrue(eventos[-1]["sucesso"])

    def test_observador_nao_muda_resultado_e_e_restaurado(self):
        def falhar(evento):
            raise RuntimeError("observador indisponível")
        with observar_medicoes(falhar), medir_etapa([], "teste"):
            resultado = 42
        eventos = []
        with observar_medicoes(eventos.append), medir_etapa([], "outra"):
            pass
        self.assertEqual(resultado, 42)
        self.assertEqual(len(eventos), 2)
        self.assertEqual(eventos[0]["etapa"], "outra")

    def test_observadores_isolados_por_thread(self):
        def tarefa(nome):
            eventos = []
            with observar_medicoes(eventos.append), medir_etapa([], nome):
                pass
            return eventos
        with ThreadPoolExecutor(max_workers=2) as executor:
            a, b = list(executor.map(tarefa, ["a", "b"]))
        self.assertEqual({e["etapa"] for e in a}, {"a"})
        self.assertEqual({e["etapa"] for e in b}, {"b"})

    def test_cancelamento_para_antes_da_proxima_amostra(self):
        cancelar = Event()
        concluidas = []
        def concluir(amostra, fase):
            concluidas.append(amostra)
            cancelar.set()
        relatorio = executar_benchmark([Configuracao()], ["limpeza", "conversa"],
                                       3, 0, True, cancelar=cancelar, ao_concluir=concluir)
        self.assertTrue(relatorio["interrompido"])
        self.assertEqual(len(concluidas), 1)
        self.assertEqual(len(relatorio["amostras"]), 1)


if __name__ == "__main__":
    unittest.main()
