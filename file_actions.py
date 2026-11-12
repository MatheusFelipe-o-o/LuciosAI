"""Operações locais de arquivos com prévia e autorização por proposta."""
from dataclasses import dataclass
import difflib
import os
from pathlib import Path
import shutil
import tempfile
import re
import unicodedata
from datetime import datetime

MAX_TEXT = 256_000
MAX_EDIT = 12_000
TEXT_TYPES = {".txt", ".md", ".py", ".js", ".css", ".html", ".json", ".csv", ".yaml", ".yml"}
DOCUMENT_TYPES = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages"}
OPERATIONS = {"list", "search", "read", "mkdir", "create", "edit", "copy", "move", "rename", "delete"}


class FileActionError(ValueError):
    pass


def _inside(root, path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path(root, name):
    if not isinstance(name, str) or not name or len(name) > 500 or "\x00" in name:
        raise FileActionError("Caminho inválido.")
    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive or any(part in ("..", "") for part in candidate.parts):
        raise FileActionError("Use um caminho relativo à pasta autorizada.")
    path = (root / candidate).resolve()
    if not _inside(root, path):
        raise FileActionError("O caminho sai da pasta autorizada.")
    return path


def _signature(path):
    if not path.exists():
        return None
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, path.is_dir())


@dataclass(frozen=True)
class Proposal:
    operation: str
    source: str
    target: str | None
    content: str | None
    interpretation: str
    preview: str
    source_signature: tuple | None
    target_signature: tuple | None
    query: str | None = None
    resolved_source: str = ""
    resolved_target: str | None = None


class FileActions:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileActionError("A pasta autorizada não existe.")

    def read_edit_source(self, name):
        path = _path(self.root, name)
        if not path.is_file() or path.suffix.lower() not in TEXT_TYPES or path.stat().st_size > MAX_EDIT:
            raise FileActionError("A edição exige um arquivo de texto existente de até 12 KB.")
        return path.read_text(encoding="utf-8")

    def fingerprint(self, name):
        path = _path(self.root, name)
        return str(path), _signature(path)

    def find_candidates(self, folder, query):
        """Localiza nomes aproximados sem abrir o conteúdo dos arquivos."""
        directory = _path(self.root, folder)
        if not directory.is_dir() or not isinstance(query, str) or not query.strip():
            raise FileActionError("Informe uma pasta e um nome para a busca.")
        def normalize(value):
            value = unicodedata.normalize("NFKD", value.casefold())
            return "".join(ch for ch in value if not unicodedata.combining(ch))
        needle = normalize(query).strip()
        aliases = {"curriculo", "curriculum", "cv", "resume", "resumee"}
        terms = aliases if needle in aliases else {needle}
        def files():
            for parent, folders, names in os.walk(directory, followlinks=False):
                folders[:] = [name for name in folders
                              if name not in {"node_modules", ".git", ".venv", "venv",
                                              "__pycache__", ".lucios_trash"}
                              and not (Path(parent) / name).is_symlink()]
                for name in names:
                    yield Path(parent) / name
        matches = []
        for path in files():
            if not path.is_file() or path.is_symlink() or not _inside(self.root, path.resolve()):
                continue
            stem = normalize(path.stem)
            words = set(re.findall(r"[a-z0-9]+", stem))
            matched = [term for term in terms if (term in words if len(term) <= 2 else term in stem)]
            if not matched:
                continue
            if set(matched) <= {"cv", "resume"} and path.suffix.lower() not in DOCUMENT_TYPES:
                continue
            info = path.stat()
            date = None
            iso = re.search(r"(20\d{2})[-_. ]?(0[1-9]|1[0-2])[-_. ]?([0-2]\d|3[01])", stem)
            br = re.search(r"([0-2]\d|3[01])[-_. ]?(0[1-9]|1[0-2])[-_. ]?(20\d{2})", stem)
            try:
                if iso:
                    date = datetime(int(iso[1]), int(iso[2]), int(iso[3])).date().isoformat()
                elif br:
                    date = datetime(int(br[3]), int(br[2]), int(br[1])).date().isoformat()
                else:
                    year = re.search(r"20\d{2}", stem)
                    if year:
                        date = f"{year[0]}-01-01"
            except ValueError:
                pass
            matches.append({
                "path": str(path.relative_to(self.root)),
                "extension": path.suffix.lower() or "sem extensão",
                "modified": datetime.fromtimestamp(info.st_mtime).isoformat(timespec="minutes"),
                "name_date": date,
                "reason": f"nome contém “{matched[0]}” relacionado a {query}",
            })
        matches.sort(key=lambda item: (item["extension"] in DOCUMENT_TYPES,
                                       item["name_date"] or "", item["modified"]), reverse=True)
        return matches

    def prepare(self, data):
        operation = data.get("operation")
        if operation not in OPERATIONS:
            raise FileActionError("Operação não reconhecida.")
        source_name = data.get("source")
        source = _path(self.root, source_name)
        target_name = data.get("target")
        target = _path(self.root, target_name) if target_name else None
        content = data.get("content")
        query = data.get("query")
        if operation == "search":
            if not isinstance(query, str) or not query.strip() or len(query) > 100:
                raise FileActionError("Informe o nome ou trecho do arquivo a buscar.")
            query = query.strip().casefold()
        elif query is not None:
            raise FileActionError("Esta operação não recebe busca.")
        interpretation = data.get("interpretation")
        if not isinstance(interpretation, str) or not interpretation.strip() or len(interpretation) > 500:
            raise FileActionError("A interpretação da ação é obrigatória.")
        if operation in {"create", "edit"}:
            limit = MAX_EDIT if operation == "edit" else MAX_TEXT
            if not isinstance(content, str) or len(content.encode("utf-8")) > limit:
                raise FileActionError("Conteúdo ausente ou grande demais.")
            if source.suffix.lower() not in TEXT_TYPES:
                raise FileActionError("Edição permitida somente para arquivos de texto conhecidos.")
        elif content is not None:
            raise FileActionError("Esta operação não recebe conteúdo.")
        if operation in {"copy", "move", "rename"}:
            if target is None or target == source:
                raise FileActionError("Informe um destino diferente.")
            if target.exists():
                raise FileActionError("O destino já existe; sobrescrita não é permitida.")
            if not target.parent.is_dir():
                raise FileActionError("A pasta de destino não existe.")
        elif target is not None:
            raise FileActionError("Esta operação não recebe destino.")
        if operation in {"read", "edit", "copy", "move", "rename", "delete"} and not source.is_file():
            raise FileActionError("O arquivo de origem não existe.")
        if operation in {"list", "search"} and not source.is_dir():
            raise FileActionError("A pasta não existe.")
        if operation in {"create", "mkdir"} and source.exists():
            raise FileActionError("O destino já existe.")
        if operation in {"create", "mkdir"} and not source.parent.is_dir():
            raise FileActionError("A pasta superior não existe.")
        if operation == "read" and source.stat().st_size > MAX_TEXT:
            raise FileActionError("Arquivo grande demais para leitura no chat.")
        preview = f"{operation}: {source_name}" + (f" → {target_name}" if target_name else "")
        if operation == "edit":
            if source.stat().st_size > MAX_EDIT:
                raise FileActionError("Arquivo grande demais para edição.")
            before = source.read_text(encoding="utf-8")
            preview = "".join(difflib.unified_diff(before.splitlines(True), content.splitlines(True),
                                                    fromfile=source_name, tofile=source_name))
            if len(preview) > 12000:
                preview = preview[:12000] + "\n… prévia limitada"
        if operation == "create":
            preview += f" ({len(content.encode('utf-8'))} bytes)"
        return Proposal(operation, source_name, target_name, content, interpretation.strip(),
                        preview, _signature(source), _signature(target) if target else None, query,
                        str(source), str(target) if target else None)

    def execute(self, proposal):
        source = _path(self.root, proposal.source)
        target = _path(self.root, proposal.target) if proposal.target else None
        if (str(source) != proposal.resolved_source
                or (target and str(target) != proposal.resolved_target)
                or _signature(source) != proposal.source_signature
                or (target and _signature(target) != proposal.target_signature)):
            raise FileActionError("Os arquivos mudaram desde a prévia. Solicite uma nova confirmação.")
        op = proposal.operation
        if op == "list":
            names = sorted(p.name + ("/" if p.is_dir() else "") for p in source.iterdir())
            return "\n".join(names[:100]) or "Pasta vazia."
        if op == "search":
            names = [item["path"] for item in self.find_candidates(proposal.source, proposal.query)]
            if not names:
                return "Nenhum arquivo encontrado."
            listing = "\n".join(names[:100])
            extra = f"\n… e mais {len(names) - 100}." if len(names) > 100 else ""
            return f"{len(names)} arquivo(s) encontrado(s):\n{listing}{extra}"
        if op == "read":
            return source.read_text(encoding="utf-8")[:MAX_TEXT]
        if op == "mkdir":
            source.mkdir()
        elif op in {"create", "edit"}:
            fd, temp_name = tempfile.mkstemp(prefix=".lucios-", dir=source.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
                    output.write(proposal.content)
                if op == "create":
                    # Falha se outro processo criou o destino após a verificação.
                    os.link(temp_name, source)
                else:
                    if _signature(source) != proposal.source_signature:
                        raise FileActionError("O arquivo mudou desde a prévia.")
                    os.replace(temp_name, source)
            finally:
                Path(temp_name).unlink(missing_ok=True)
        elif op == "copy":
            created = False
            try:
                with source.open("rb") as src:
                    with target.open("xb") as dst:
                        created = True
                        shutil.copyfileobj(src, dst)
            except Exception:
                if created:
                    target.unlink(missing_ok=True)
                raise
        elif op in {"move", "rename"}:
            if target.exists():
                raise FileActionError("O destino já existe.")
            source.rename(target)
        elif op == "delete":
            trash = _path(self.root, ".lucios_trash")
            trash.mkdir(exist_ok=True)
            destination = trash / (source.name + "-" + os.urandom(4).hex())
            source.rename(destination)
            return f"Arquivo movido para a lixeira local: {destination.relative_to(self.root)}"
        return f"Ação concluída: {proposal.preview[:300]}"
