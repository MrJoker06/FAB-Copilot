from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    session_id: str | None = None
    client_message_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    thinking: StrictBool = False


class StreamTelemetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=8, max_length=64)
    read_chunks: int = Field(default=0, ge=0, le=100000)
    progress_events: int = Field(default=0, ge=0, le=100000)
    answer_events: int = Field(default=0, ge=0, le=100000)
    answer_chars: int = Field(default=0, ge=0, le=1000000)
    max_read_gap_ms: float = Field(default=0, ge=0, le=3600000)
    max_buffer_pending: int = Field(default=0, ge=0, le=1000000)
    render_frames: int = Field(default=0, ge=0, le=100000)
    max_render_ms: float = Field(default=0, ge=0, le=3600000)
    total_render_ms: float = Field(default=0, ge=0, le=3600000)
    hidden_resumes: int = Field(default=0, ge=0, le=10000)
    stable_appends: int = Field(default=0, ge=0, le=100000)
    tail_replacements: int = Field(default=0, ge=0, le=100000)
    stream_resets: int = Field(default=0, ge=0, le=10000)
    max_tail_chars: int = Field(default=0, ge=0, le=1000000)
    max_visible_step: int = Field(default=0, ge=0, le=1000000)
    final_match: bool = False
    duration_ms: float = Field(default=0, ge=0, le=3600000)


class ModelConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=2, max_length=64)


class ModelCapabilitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    streaming: StrictBool = True
    tool_calls: StrictBool = True
    thinking: StrictBool = False
    native_multimodal: StrictBool = False


class AdminModelPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=2, max_length=100)
    provider: str = Field(pattern=r"^(deepseek|openai-compatible)$")
    provider_model: str = Field(min_length=2, max_length=120)
    base_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    capabilities: ModelCapabilitiesRequest = Field(default_factory=ModelCapabilitiesRequest)


class AdminModelStatusRequest(BaseModel):
    status: str = Field(pattern=r"^(published|retired)$")


class AdminModelCapabilitiesRequest(BaseModel):
    """An explicit, complete administrator declaration (no extension keys)."""
    model_config = ConfigDict(extra="forbid")
    streaming: StrictBool
    tool_calls: StrictBool
    thinking: StrictBool
    native_multimodal: StrictBool


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class BulkSessionDeleteRequest(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=200)


class PersonalSearchPreviewRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
