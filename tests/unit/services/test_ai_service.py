"""
Tests for AIService - intent classification and date parsing.

Following TDD: tests verify the behavior of existing implementation.
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from application.services.ai_service import AIService, ActionType, ParsedIntent


class TestAIServiceDateParsing:
    """Tests for _parse_relative_date method - critical for user messages."""

    def setup_method(self):
        self.service = AIService()

    def test_parse_el_miercoles_dd_mm_without_time(self):
        """Test 'el miercoles 3/11' without explicit time defaults to midnight."""
        text = "el miercoles 3/11 tengo que evaluar orales en 2B"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.year == 2026
        assert result.month == 11
        assert result.day == 3
        assert result.hour == 0
        assert result.minute == 0
        assert result.tzinfo is not None

    def test_parse_miercoles_dd_mm_with_time(self):
        """Test 'miercoles 3/11 a las 12:50hs' with explicit time."""
        text = "miercoles 3/11 a las 12:50hs evaluacion a 2B"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.year == 2026
        assert result.month == 11
        assert result.day == 3
        assert result.hour == 12
        assert result.minute == 50
        assert result.tzinfo is not None

    def test_parse_el_miercoles_dd_mm_with_time(self):
        """Test 'El miércoles 3/11 a las 12hs' with accent and 'El' prefix."""
        text = "El miércoles 3/11 a las 12hs entrega de examenes"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.year == 2026
        assert result.month == 11
        assert result.day == 3
        assert result.hour == 12
        assert result.minute == 0
        assert result.tzinfo is not None

    def test_parse_mañana_with_time(self):
        """Test 'mañana 9hs' relative date."""
        text = "mañana 9hs reunion"
        result = self.service._parse_relative_date(text)

        assert result is not None
        # mañana = tomorrow
        assert result.hour == 9
        assert result.minute == 0

    def test_parse_hoy_with_time(self):
        """Test 'hoy 15:30' relative date."""
        text = "hoy 15:30 llamada"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.hour == 15
        assert result.minute == 30

    def test_parse_pasado_mañana_with_time(self):
        """Test 'pasado mañana 10hs' relative date."""
        text = "pasado mañana 10hs"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.hour == 10
        assert result.minute == 0

    def test_parse_el_dd_mm_with_time(self):
        """Test 'el 25/12 a las 10' format."""
        text = "el 25/12 a las 10"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.month == 12
        assert result.day == 25
        assert result.hour == 10
        assert result.minute == 0

    def test_parse_martes_dd_mm_with_time(self):
        """Test 'martes 12/11 a las 14hs' format."""
        text = "martes 12/11 a las 14hs"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.month == 11
        assert result.day == 12
        assert result.hour == 14
        assert result.minute == 0

    def test_parse_text_without_date_returns_none(self):
        """Test text without date returns None."""
        text = "hola como estas"
        result = self.service._parse_relative_date(text)

        assert result is None

    def test_parse_returns_timezone_aware_datetime(self):
        """Test that returned datetime is timezone-aware (Argentina)."""
        text = "mañana 9hs"
        result = self.service._parse_relative_date(text)

        assert result is not None
        assert result.tzinfo is not None
        # Should be Argentina timezone
        assert str(result.tzinfo) == "America/Argentina/Buenos_Aires"


class TestAIServiceNormalizeResult:
    """Tests for _normalize_result method - handles AI response normalization."""

    def setup_method(self):
        self.service = AIService()

    def test_normalize_handles_fecha_field(self):
        """Test that _normalize_result handles 'fecha' field (abbreviated) from AI."""
        result = {
            "accion": "EVENTO",
            "detalles": "Reunión con Juan",
            "fecha": "2026-11-03 12:00",  # AI returns 'fecha' not 'fecha_hora'
            "recurrencia": None,
            "prioridad": 0,
            "tags": ["trabajo"],
            "confianza": 0.9,
        }

        intent = self.service._normalize_result(result, "Reunión con Juan mañana 12hs")

        assert intent.accion == ActionType.EVENTO
        assert intent.detalles == "Reunión con Juan"
        assert intent.fecha_hora is not None
        assert intent.fecha_hora.year == 2026
        assert intent.fecha_hora.month == 11
        assert intent.fecha_hora.day == 3
        assert intent.fecha_hora.hour == 12

    def test_normalize_handles_fecha_hora_field(self):
        """Test that _normalize_result handles 'fecha_hora' field (full name) from AI."""
        result = {
            "accion": "EVENTO",
            "detalles": "Reunión con Juan",
            "fecha_hora": "2026-11-03 14:00",
            "recurrencia": None,
            "prioridad": 1,
            "tags": ["trabajo"],
            "confianza": 0.95,
        }

        intent = self.service._normalize_result(result, "Reunión con Juan mañana 14hs urgente")

        assert intent.accion == ActionType.EVENTO
        assert intent.fecha_hora is not None
        assert intent.fecha_hora.hour == 14
        assert intent.prioridad == 1

    def test_normalize_prefers_fecha_hora_over_fecha(self):
        """Test that fecha_hora takes precedence when both present."""
        result = {
            "accion": "EVENTO",
            "detalles": "Test",
            "fecha_hora": "2026-11-03 10:00",
            "fecha": "2026-11-03 15:00",  # Different time - should be ignored
            "prioridad": 0,
            "tags": [],
        }

        intent = self.service._normalize_result(result, "test")

        assert intent.fecha_hora.hour == 10  # fecha_hora wins

    def test_normalize_handles_null_fecha_hora(self):
        """Test that null/None fecha_hora is handled correctly."""
        result = {
            "accion": "NOTA",
            "detalles": "Clave wifi",
            "fecha_hora": None,
            "prioridad": 0,
            "tags": [],
        }

        intent = self.service._normalize_result(result, "Clave wifi es 1234")

        assert intent.accion == ActionType.NOTA
        assert intent.fecha_hora is None

    def test_normalize_handles_string_null(self):
        """Test that 'null' string is treated as None."""
        result = {
            "accion": "NOTA",
            "detalles": "Clave wifi",
            "fecha_hora": "null",  # String null
            "prioridad": 0,
            "tags": [],
        }

        intent = self.service._normalize_result(result, "Clave wifi es 1234")

        assert intent.fecha_hora is None

    def test_normalize_handles_priority_bounds(self):
        """Test priority is clamped to -1, 0, 1."""
        # Test priority > 1 clamped to 1
        result_high = {
            "accion": "EVENTO",
            "detalles": "Test",
            "fecha_hora": "2026-11-03 10:00",
            "prioridad": 5,  # Should clamp to 1
            "tags": [],
        }
        intent = self.service._normalize_result(result_high, "test")
        assert intent.prioridad == 1

        # Test priority < -1 clamped to -1
        result_low = {
            "accion": "EVENTO",
            "detalles": "Test",
            "fecha_hora": "2026-11-03 10:00",
            "prioridad": -5,  # Should clamp to -1
            "tags": [],
        }
        intent = self.service._normalize_result(result_low, "test")
        assert intent.prioridad == -1

    def test_normalize_handles_tags_cleaning(self):
        """Test tags are cleaned (lowercase, no #)."""
        result = {
            "accion": "EVENTO",
            "detalles": "Test",
            "fecha_hora": "2026-11-03 10:00",
            "prioridad": 0,
            "tags": ["#TRABAJO", "Urgente", "#casa"],  # Mixed case with #
        }

        intent = self.service._normalize_result(result, "test")

        assert intent.tags == ["trabajo", "urgente", "casa"]

    def test_normalize_handles_invalid_action(self):
        """Test invalid action defaults to ERROR."""
        result = {
            "accion": "INVALID_ACTION",
            "detalles": "Test",
            "fecha_hora": None,
            "prioridad": 0,
            "tags": [],
        }

        intent = self.service._normalize_result(result, "test")

        assert intent.accion == ActionType.ERROR


class TestAIServiceIntegration:
    """Integration tests for classify_intent (requires Groq API key)."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        True,  # Set to False to run with real API
        reason="Requires GROQ_API_KEY environment variable"
    )
    async def test_classify_intent_evento_with_date(self):
        """Test classify_intent parses event with date."""
        service = AIService()
        # This would require real API key
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])