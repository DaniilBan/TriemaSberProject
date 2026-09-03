from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class MaskedEntity(BaseModel):
    original_text: str
    masked_text: str
    start_pos: int
    end_pos: int
    entity_type: str  # 'INN', 'PHONE', 'EMAIL', 'COMPANY_NAME' и т.д.
    confidence: float  # 0.0-1.0


class ParsedDocument(BaseModel):
    filename: str
    file_type: str  # 'docx', 'xlsx', 'pdf'
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