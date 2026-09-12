from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class MaskedEntity(BaseModel):
    original_text: str
    masked_text: str
    start_pos: int
    end_pos: int
    entity_type: str
    confidence: float


class ParsedDocument(BaseModel):
    filename: str
    file_type: str
    full_text: str
    pages_or_sheets: Dict[str, str]
    tables: Optional[List[Dict[str, Any]]]
    metadata: Dict[str, Any]


class ParserInterface(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument:
        pass


class LLMInterface(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        pass

    @abstractmethod
    def get_embedding(self, text: str) -> List[float]:
        pass