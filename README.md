# LuciosAI

Assistente conversacional em português que usa modelos locais do [Ollama](https://ollama.com/). Pode ser usado pelo terminal ou por uma interface web no próprio computador.

> **Estado:** projeto pessoal em desenvolvimento. A interface web foi feita para uso local, não para hospedagem pública.

## O que já funciona

- **Chat local:** converse com o modelo pela interface web ou pelo terminal.
- **Histórico local:** conversas podem ser retomadas, pesquisadas e excluídas na interface web.
- **Memória sob demanda:** o assistente consulta registros anteriores quando o pedido indica essa intenção; o botão **Salvar na memória** gera um resumo separado do histórico completo.
- **Modelos locais:** seleção automática ou escolha de um modelo instalado no Ollama para as respostas.
- **Performance Lab:** painel local para observar hardware e executar benchmarks por etapa.

O modo **Arquivos** está em desenvolvimento e aprimoramento. Sua interface e suas operações ainda podem mudar.

## Requisitos

- Python 3.12.
- Ollama instalado e em execução.
- Modelo `llama3.2` instalado, ou outro modelo definido em `LUCIOS_MODELO`.

O exemplo abaixo usa PowerShell no Windows.

### Hardware para os modelos

O aplicativo é leve; o consumo principal vem do modelo carregado pelo Ollama. Estas são **estimativas práticas** para as versões quantizadas abaixo, não uma garantia de desempenho:

| Modelo | Arquivo do modelo | RAM sugerida | GPU |
| --- | ---: | ---: | --- |
| [`llama3.2` (3B, padrão)](https://ollama.com/library/llama3.2) | cerca de 2 GB | 8 GB ou mais | Opcional; pode rodar só na CPU. |
| [`qwen3.5:9b-q4_K_M` (9B, Q4)](https://ollama.com/library/qwen3.5/tags) | cerca de 6,6 GB | 16 GB ou mais; 24 GB dão mais folga | Cerca de 10 GB de VRAM ou mais dão folga para manter o modelo na GPU. Com 6 GB, parte pode ficar na RAM/CPU e a resposta ser mais lenta. |

Há outras variantes de 9B Q4. A variante `hf.co/Auter/Qwen3.5-9B-N-S:Q4_K_M`, por exemplo, ocupa cerca de **5,6 GB em disco**; os requisitos de execução ainda dependem do contexto e da memória disponível.

Reserve espaço adicional no disco para o Ollama, o ambiente Python e outros modelos. O uso de memória muda conforme o tamanho do contexto, a versão do modelo e o que mais estiver aberto. O Lucios configura **4.096 tokens de contexto** por padrão.

## Instalação

Na pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
ollama pull llama3.2
```

O comando `ollama pull` precisa de internet apenas para baixar o modelo. Depois, mantenha o serviço Ollama em execução para conversar com ele.

## Como usar

Para abrir a interface web:

```powershell
python web_app.py
```

Acesse **http://127.0.0.1:8000** no navegador. Para usar o terminal:

```powershell
python main.py
```

No terminal, digite `sair` para encerrar e tentar salvar um resumo da conversa. O comando `limpar` apaga o contexto da conversa em andamento.

### Performance Lab

O painel pode ser aberto pela interface web. Para executá-lo separadamente na porta **8001**:

```powershell
python -m pip install -r benchmarks/requirements.txt
python -m benchmarks.web
```

## Privacidade e limites

O chat web escuta em `127.0.0.1` e foi projetado para uso no próprio computador. **Não exponha essa interface à internet ou à rede local sem implementar autenticação e revisar a segurança.**

O histórico web fica em `local_data/conversations.sqlite3`; os resumos de memória ficam em `memoria_lucios.txt`. Esses arquivos são locais, podem conter dados pessoais e são ignorados pelo Git. O histórico não possui criptografia em repouso nem expiração automática.

As respostas do modelo podem conter erros. Ao experimentar o modo **Arquivos**, confira a interpretação, os caminhos e a prévia antes de confirmar qualquer ação.

## Desenvolvimento

Testes automatizados, sem baixar modelos nem usar memórias pessoais:

```powershell
python -B -m unittest discover -q
```

Para verificar a lógica da interface web, se o Node.js estiver instalado:

```powershell
node tests/test_chat_ui.js
```

Os testes de inferência real exigem um serviço Ollama ativo. A execução completa dos testes HTTP também precisa permitir conexões locais.

## Licença

Ainda não foi definida uma licença para distribuição ou reutilização do código.
