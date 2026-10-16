"""TEACHER module (P1): multiple AI teacher profiles — independent, duplicable,
switchable, persisted.  Pure data + validation + one JSON file; NO gateway/audio
imports, NOT another LLM."""

from modules.teacher.store import (  # noqa: F401
    DEFAULT_TEACHER_ID, LANGUAGES, LANGUAGE_LABELS, STYLES, STYLE_LABELS,
    SUBJECTS, SUBJECT_LABELS, VOICE_MODES, Duplicate, FrozenTeacher, NotFound,
    TeacherInvalid, TeacherStore, render_system_instruction,
)
