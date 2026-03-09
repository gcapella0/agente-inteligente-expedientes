"""Tests para OcrService y OcrAgent."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.ocr_service import OcrService, SUPPORTED_EXTENSIONS
from src.agents.ocr_agent import OcrAgent


# ---------------------------------------------------------------------------
# Helpers: JSON de ejemplo que simula la salida de docTR result.export()
# ---------------------------------------------------------------------------

def build_doctr_export(
    words: list[tuple[str, float]] | None = None,
    pages: int = 1,
    language: str = "es",
) -> dict:
    """Construye un dict simulando result.export() de docTR.

    Args:
        words: Lista de tuplas (texto, confianza). Si es None, se usan defaults.
        pages: Cantidad de páginas a generar.
        language: Idioma reportado.
    """
    if words is None:
        words = [("República", 0.97), ("Bolivariana", 0.95), ("de", 0.99), ("Venezuela", 0.96)]

    word_dicts = [
        {
            "value": text,
            "confidence": conf,
            "geometry": [[0.0, 0.0], [0.1, 0.05]],
        }
        for text, conf in words
    ]

    page_template = {
        "dimensions": [842, 595],
        "orientation": {"value": 0, "confidence": 0.98},
        "language": {"value": language, "confidence": 0.95},
        "blocks": [
            {
                "geometry": [[0.0, 0.0], [1.0, 1.0]],
                "lines": [
                    {
                        "geometry": [[0.0, 0.0], [1.0, 0.05]],
                        "words": word_dicts,
                    }
                ],
            }
        ],
    }

    return {"pages": [page_template for _ in range(pages)]}


def build_doctr_render(words: list[tuple[str, float]] | None = None) -> str:
    """Construye el texto que retornaría result.render()."""
    if words is None:
        words = [("República", 0.97), ("Bolivariana", 0.95), ("de", 0.99), ("Venezuela", 0.96)]
    return " ".join(w[0] for w in words)


class FakeDoctrResult:
    """Simula el objeto result retornado por model(doc)."""

    def __init__(self, words=None, pages=1, language="es"):
        self._words = words
        self._pages = pages
        self._language = language

    def export(self) -> dict:
        return build_doctr_export(self._words, self._pages, self._language)

    def render(self) -> str:
        return build_doctr_render(self._words)


class FakeDoctrModel:
    """Simula ocr_predictor(pretrained=True)."""

    def __init__(self, words=None, pages=1, language="es", should_fail=False):
        self._words = words
        self._pages = pages
        self._language = language
        self._should_fail = should_fail

    def __call__(self, doc):
        if self._should_fail:
            raise RuntimeError("Error simulado de docTR")
        return FakeDoctrResult(self._words, self._pages, self._language)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_ocr_service(monkeypatch):
    """Retorna un OcrService con el modelo mockeado (no descarga pesos reales)."""

    def factory(words=None, pages=1, language="es", should_fail=False):
        fake_model = FakeDoctrModel(words, pages, language, should_fail)

        with patch.object(OcrService, "__init__", lambda self: None):
            service = OcrService()
            service.model = fake_model
        return service

    return factory


@pytest.fixture
def sample_input_dir(tmp_path):
    """Crea una estructura de carpetas simulando data/input/ con archivos de prueba."""

    def factory(
        carpetas: dict[str, list[tuple[str, bytes]]] | None = None,
    ) -> Path:
        if carpetas is None:
            carpetas = {
                "Maria_Elena_Garcia": [
                    ("titulo_universitario.pdf", b"%PDF-fake-content"),
                    ("notas_pregrado.jpg", b"\xff\xd8\xff\xe0fake-jpg"),
                    ("info_mail_Maria_Elena_Garcia.txt", b"Correo de prueba"),
                ],
            }
        for folder_name, files in carpetas.items():
            folder = tmp_path / folder_name
            folder.mkdir(parents=True, exist_ok=True)
            for filename, content in files:
                (folder / filename).write_bytes(content)
        return tmp_path

    return factory


# ===========================================================================
# Tests para OcrService.calcular_confianza_promedio
# ===========================================================================


class TestCalcularConfianzaPromedio:
    """Tests del método estático calcular_confianza_promedio."""

    def test_confianza_con_multiples_palabras(self):
        words = [("a", 0.90), ("b", 0.80), ("c", 0.70)]
        json_output = build_doctr_export(words)
        resultado = OcrService.calcular_confianza_promedio(json_output)
        assert resultado == round((0.90 + 0.80 + 0.70) / 3, 4)

    def test_confianza_sin_palabras(self):
        json_output = {"pages": [{"blocks": [{"lines": [{"words": []}]}]}]}
        assert OcrService.calcular_confianza_promedio(json_output) == 0.0

    def test_confianza_sin_paginas(self):
        assert OcrService.calcular_confianza_promedio({"pages": []}) == 0.0

    def test_confianza_dict_vacio(self):
        assert OcrService.calcular_confianza_promedio({}) == 0.0

    def test_confianza_una_sola_palabra(self):
        json_output = build_doctr_export([("texto", 0.9512)])
        assert OcrService.calcular_confianza_promedio(json_output) == 0.9512

    def test_confianza_redondeo_4_decimales(self):
        words = [("a", 0.333), ("b", 0.666)]
        json_output = build_doctr_export(words)
        resultado = OcrService.calcular_confianza_promedio(json_output)
        assert resultado == round((0.333 + 0.666) / 2, 4)

    def test_confianza_multiples_paginas(self):
        json_output = build_doctr_export([("a", 0.80)], pages=3)
        resultado = OcrService.calcular_confianza_promedio(json_output)
        # 3 páginas, cada una con 1 palabra de confianza 0.80
        assert resultado == 0.80

    def test_confianza_perfecta(self):
        words = [("a", 1.0), ("b", 1.0)]
        json_output = build_doctr_export(words)
        assert OcrService.calcular_confianza_promedio(json_output) == 1.0

    def test_confianza_cero(self):
        words = [("a", 0.0), ("b", 0.0)]
        json_output = build_doctr_export(words)
        assert OcrService.calcular_confianza_promedio(json_output) == 0.0


# ===========================================================================
# Tests para OcrService.contar_palabras
# ===========================================================================


class TestContarPalabras:
    """Tests del método estático contar_palabras."""

    def test_contar_palabras_basico(self):
        json_output = build_doctr_export([("a", 0.9), ("b", 0.8), ("c", 0.7)])
        assert OcrService.contar_palabras(json_output) == 3

    def test_contar_sin_palabras(self):
        assert OcrService.contar_palabras({"pages": []}) == 0

    def test_contar_dict_vacio(self):
        assert OcrService.contar_palabras({}) == 0

    def test_contar_multiples_paginas(self):
        json_output = build_doctr_export([("a", 0.9), ("b", 0.8)], pages=4)
        # 4 páginas × 2 palabras = 8
        assert OcrService.contar_palabras(json_output) == 8

    def test_contar_una_palabra(self):
        json_output = build_doctr_export([("solo", 0.95)])
        assert OcrService.contar_palabras(json_output) == 1


# ===========================================================================
# Tests para OcrService.process_file
# ===========================================================================


class TestOcrServiceProcessFile:
    """Tests del método process_file con modelo mockeado."""

    def test_procesa_pdf_exitosamente(self, fake_ocr_service, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-fake")
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            resultado = service.process_file(pdf)

        mock_df.from_pdf.assert_called_once_with(str(pdf))
        assert resultado["texto_completo"] == build_doctr_render()
        assert resultado["paginas"] == 1
        assert resultado["idioma_detectado"] == "es"
        assert resultado["palabras_detectadas"] == 4
        assert isinstance(resultado["confianza_promedio"], float)
        assert isinstance(resultado["json_export"], dict)

    def test_procesa_jpg_exitosamente(self, fake_ocr_service, tmp_path):
        img = tmp_path / "foto.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_images.return_value = "fake_doc"
            resultado = service.process_file(img)

        mock_df.from_images.assert_called_once_with([str(img)])
        assert resultado["paginas"] == 1

    def test_procesa_jpeg_como_imagen(self, fake_ocr_service, tmp_path):
        img = tmp_path / "foto.jpeg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_images.return_value = "fake_doc"
            service.process_file(img)

        mock_df.from_images.assert_called_once_with([str(img)])

    def test_procesa_png_como_imagen(self, fake_ocr_service, tmp_path):
        img = tmp_path / "foto.png"
        img.write_bytes(b"\x89PNG")
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_images.return_value = "fake_doc"
            service.process_file(img)

        mock_df.from_images.assert_called_once_with([str(img)])

    def test_extension_no_soportada_lanza_valueerror(self, fake_ocr_service, tmp_path):
        doc = tmp_path / "archivo.docx"
        doc.write_bytes(b"fake")
        service = fake_ocr_service()

        with pytest.raises(ValueError, match="no soportada"):
            service.process_file(doc)

    def test_extension_txt_no_soportada(self, fake_ocr_service, tmp_path):
        doc = tmp_path / "info.txt"
        doc.write_bytes(b"texto")
        service = fake_ocr_service()

        with pytest.raises(ValueError, match="no soportada"):
            service.process_file(doc)

    def test_extension_mayuscula_funciona(self, fake_ocr_service, tmp_path):
        """Extensiones como .PDF o .JPG deben funcionar (se normalizan a minúscula)."""
        pdf = tmp_path / "doc.PDF"
        pdf.write_bytes(b"%PDF-fake")
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            resultado = service.process_file(pdf)

        assert resultado["paginas"] == 1

    def test_multiples_paginas(self, fake_ocr_service, tmp_path):
        pdf = tmp_path / "largo.pdf"
        pdf.write_bytes(b"%PDF-fake")
        service = fake_ocr_service(pages=5)

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            resultado = service.process_file(pdf)

        assert resultado["paginas"] == 5

    def test_idioma_detectado_desde_json(self, fake_ocr_service, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF")
        service = fake_ocr_service(language="en")

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            resultado = service.process_file(pdf)

        assert resultado["idioma_detectado"] == "en"

    def test_idioma_desconocido_si_falta(self, fake_ocr_service, tmp_path):
        """Si el JSON no tiene info de idioma, retorna 'desconocido'."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF")
        service = fake_ocr_service()

        # Crear un resultado sin campo language
        fake_result = FakeDoctrResult()
        original_export = fake_result.export()
        for page in original_export["pages"]:
            del page["language"]

        mock_result = MagicMock()
        mock_result.export.return_value = original_export
        mock_result.render.return_value = "texto"
        service.model = MagicMock(return_value=mock_result)

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            resultado = service.process_file(pdf)

        assert resultado["idioma_detectado"] == "desconocido"

    def test_doctr_falla_propaga_excepcion(self, fake_ocr_service, tmp_path):
        pdf = tmp_path / "corrupto.pdf"
        pdf.write_bytes(b"corrupto")
        service = fake_ocr_service(should_fail=True)

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            with pytest.raises(RuntimeError, match="Error simulado"):
                service.process_file(pdf)

    def test_claves_retornadas(self, fake_ocr_service, tmp_path):
        """Verifica que el dict retornado contiene todas las claves esperadas."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF")
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile") as mock_df:
            mock_df.from_pdf.return_value = "fake_doc"
            resultado = service.process_file(pdf)

        expected_keys = {
            "texto_completo", "json_export", "confianza_promedio",
            "paginas", "idioma_detectado", "palabras_detectadas",
        }
        assert set(resultado.keys()) == expected_keys


# ===========================================================================
# Tests para OcrAgent.process_directory
# ===========================================================================


class TestOcrAgentProcessDirectory:
    """Tests del OcrAgent con OcrService mockeado."""

    def test_procesa_archivos_en_subcarpetas(self, fake_ocr_service, sample_input_dir):
        """Procesa PDFs y JPGs, ignora TXTs."""
        input_dir = sample_input_dir()
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory(input_dir)

        # Maria_Elena_Garcia tiene 1 PDF + 1 JPG (el .txt se ignora)
        assert len(resultados) == 2
        nombres = {r["archivo_nombre"] for r in resultados}
        assert "titulo_universitario.pdf" in nombres
        assert "notas_pregrado.jpg" in nombres
        assert "info_mail_Maria_Elena_Garcia.txt" not in nombres

    def test_directorio_inexistente_retorna_vacio(self, fake_ocr_service, tmp_path):
        service = fake_ocr_service()
        agent = OcrAgent(service)
        resultados = agent.process_directory(tmp_path / "no_existe")
        assert resultados == []

    def test_directorio_vacio_retorna_vacio(self, fake_ocr_service, tmp_path):
        service = fake_ocr_service()
        agent = OcrAgent(service)
        resultados = agent.process_directory(tmp_path)
        assert resultados == []

    def test_subcarpeta_sin_archivos_procesables(self, fake_ocr_service, sample_input_dir):
        """Una subcarpeta con solo .txt no genera resultados."""
        input_dir = sample_input_dir({
            "Carpeta_Solo_Txt": [
                ("info_mail.txt", b"solo texto"),
                ("notas.txt", b"mas texto"),
            ],
        })
        service = fake_ocr_service()
        agent = OcrAgent(service)
        resultados = agent.process_directory(input_dir)
        assert resultados == []

    def test_multiples_subcarpetas(self, fake_ocr_service, sample_input_dir):
        input_dir = sample_input_dir({
            "Docente_A": [("titulo.pdf", b"%PDF-A")],
            "Docente_B": [("cedula.jpg", b"\xff\xd8\xff\xe0B")],
            "Docente_C": [("notas.png", b"\x89PNGC")],
        })
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory(input_dir)

        assert len(resultados) == 3
        carpetas = {r["carpeta_origen"] for r in resultados}
        assert carpetas == {"Docente_A", "Docente_B", "Docente_C"}

    def test_metadatos_del_resultado(self, fake_ocr_service, sample_input_dir):
        """Verifica que cada resultado contiene todos los metadatos esperados."""
        contenido_pdf = b"%PDF-test-content"
        input_dir = sample_input_dir({
            "Test_Docente": [("doc.pdf", contenido_pdf)],
        })
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory(input_dir)

        assert len(resultados) == 1
        r = resultados[0]
        assert r["archivo_nombre"] == "doc.pdf"
        assert r["carpeta_origen"] == "Test_Docente"
        assert r["formato"] == "pdf"
        assert r["tamano_bytes"] == len(contenido_pdf)
        assert r["hash_sha256"] == hashlib.sha256(contenido_pdf).hexdigest()
        assert r["ocr_resultado"] is not None
        assert isinstance(r["archivo_path"], Path)

    def test_hash_sha256_es_correcto(self, fake_ocr_service, sample_input_dir):
        contenido = b"contenido-unico-para-hash"
        input_dir = sample_input_dir({
            "Hash_Test": [("archivo.jpg", contenido)],
        })
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory(input_dir)

        expected_hash = hashlib.sha256(contenido).hexdigest()
        assert resultados[0]["hash_sha256"] == expected_hash

    def test_formato_se_normaliza_a_minuscula(self, fake_ocr_service, sample_input_dir):
        input_dir = sample_input_dir({
            "Mayuscula": [("DOC.PDF", b"%PDF")],
        })
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory(input_dir)

        assert resultados[0]["formato"] == "pdf"

    def test_fallo_ocr_continua_con_siguiente(self, fake_ocr_service, sample_input_dir):
        """Si un archivo falla, el pipeline continúa con el siguiente."""
        input_dir = sample_input_dir({
            "Mixto": [
                ("bueno.jpg", b"\xff\xd8\xff\xe0ok"),
                ("malo.pdf", b"corrupto"),
            ],
        })

        # Servicio que falla solo para el PDF
        service = fake_ocr_service()
        call_count = 0
        original_process = service.process_file

        def process_selectivo(path):
            nonlocal call_count
            call_count += 1
            if path.suffix == ".pdf":
                raise RuntimeError("PDF corrupto")
            return original_process(path)

        service.process_file = process_selectivo

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory(input_dir)

        assert len(resultados) == 2
        # El JPG tiene resultado, el PDF no
        pdf_result = next(r for r in resultados if r["formato"] == "pdf")
        jpg_result = next(r for r in resultados if r["formato"] == "jpg")
        assert pdf_result["ocr_resultado"] is None
        assert jpg_result["ocr_resultado"] is not None

    def test_fallo_ocr_registra_audit_log(self, fake_ocr_service, sample_input_dir, monkeypatch):
        """Verifica que un fallo de OCR genera audit_log con accion='ocr_fallido'."""
        input_dir = sample_input_dir({
            "Fallo": [("corrupto.pdf", b"bad")],
        })
        service = fake_ocr_service(should_fail=True)

        audit_calls: list[tuple] = []

        def fake_audit_log(agente, accion, resultado, **kwargs):
            audit_calls.append((agente, accion, resultado, kwargs))

        monkeypatch.setattr("src.agents.ocr_agent.audit_log", fake_audit_log)

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            agent.process_directory(input_dir)

        assert len(audit_calls) == 1
        agente, accion, resultado, kwargs = audit_calls[0]
        assert agente == "ocr"
        assert accion == "ocr_fallido"
        assert resultado == "error"
        detalle = json.loads(kwargs["detalle"])
        assert detalle["motor"] == "doctr"
        assert "error" in detalle

    def test_exito_ocr_registra_audit_log(self, fake_ocr_service, sample_input_dir, monkeypatch):
        """Verifica que un OCR exitoso genera audit_log con accion='ocr_completado'."""
        input_dir = sample_input_dir({
            "Exito": [("doc.pdf", b"%PDF")],
        })
        service = fake_ocr_service()

        audit_calls: list[tuple] = []

        def fake_audit_log(agente, accion, resultado, **kwargs):
            audit_calls.append((agente, accion, resultado, kwargs))

        monkeypatch.setattr("src.agents.ocr_agent.audit_log", fake_audit_log)

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            agent.process_directory(input_dir)

        assert len(audit_calls) == 1
        agente, accion, resultado, kwargs = audit_calls[0]
        assert agente == "ocr"
        assert accion == "ocr_completado"
        assert resultado == "ok"
        detalle = json.loads(kwargs["detalle"])
        assert detalle["motor"] == "doctr"
        assert "paginas" in detalle
        assert "confianza_promedio" in detalle
        assert "palabras_detectadas" in detalle
        assert "tiempo_procesamiento_ms" in detalle

    def test_ignora_archivos_en_raiz(self, fake_ocr_service, tmp_path):
        """Solo procesa archivos dentro de subcarpetas, no en la raíz."""
        (tmp_path / "suelto.pdf").write_bytes(b"%PDF")
        service = fake_ocr_service()
        agent = OcrAgent(service)
        resultados = agent.process_directory(tmp_path)
        assert resultados == []

    def test_usa_config_input_dir_por_defecto(self, fake_ocr_service, monkeypatch, tmp_path):
        """Si no se pasa directory, usa config.INPUT_DIR."""
        sub = tmp_path / "docente"
        sub.mkdir()
        (sub / "doc.pdf").write_bytes(b"%PDF")

        monkeypatch.setattr("src.agents.ocr_agent.config.INPUT_DIR", tmp_path)
        service = fake_ocr_service()

        with patch("src.services.ocr_service.DocumentFile"):
            agent = OcrAgent(service)
            resultados = agent.process_directory()

        assert len(resultados) == 1


# ===========================================================================
# Tests para SUPPORTED_EXTENSIONS
# ===========================================================================


class TestSupportedExtensions:
    """Verifica que las extensiones soportadas son las correctas."""

    def test_extensiones_esperadas(self):
        assert SUPPORTED_EXTENSIONS == {".pdf", ".jpg", ".jpeg", ".png"}

    @pytest.mark.parametrize("ext", [".pdf", ".jpg", ".jpeg", ".png"])
    def test_extension_esta_soportada(self, ext):
        assert ext in SUPPORTED_EXTENSIONS

    @pytest.mark.parametrize("ext", [".txt", ".docx", ".gif", ".bmp", ".tiff"])
    def test_extension_no_soportada(self, ext):
        assert ext not in SUPPORTED_EXTENSIONS
