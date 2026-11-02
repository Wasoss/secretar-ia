"""
Message handlers for Secretar-IA.
"""
from .text import recibir_texto
from .audio import recibir_audio

__all__ = ['recibir_texto', 'recibir_audio']