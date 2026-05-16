from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SanctionedEntity(Base):
    __tablename__ = "sanctioned_entities"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_sanctioned_entities_source_source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    primary_name: Mapped[str] = mapped_column(Text, nullable=False)
    programs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    legal_basis: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    country_of_registration: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    list_date: Mapped[date | None] = mapped_column(Date)
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    data_vintage: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    raw_record: Mapped[dict | None] = mapped_column(JSONB)

    aliases: Mapped[list[EntityAlias]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    vessels: Mapped[list[Vessel]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    addresses: Mapped[list[EntityAddress]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    identifiers: Mapped[list[EntityIdentifier]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    relationships_from: Mapped[list[EntityRelationship]] = relationship(
        back_populates="from_entity",
        foreign_keys="EntityRelationship.from_entity_id",
        cascade="all, delete-orphan",
    )
    relationships_to: Mapped[list[EntityRelationship]] = relationship(
        back_populates="to_entity",
        foreign_keys="EntityRelationship.to_entity_id",
        cascade="all, delete-orphan",
    )


class EntityAlias(Base):
    __tablename__ = "entity_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
    )
    alias_name: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    entity: Mapped[SanctionedEntity] = relationship(back_populates="aliases")


class Vessel(Base):
    __tablename__ = "vessels"
    __table_args__ = (
        Index(
            "ix_vessels_imo_entity_unique",
            "imo_number",
            "entity_id",
            unique=True,
            postgresql_where=text("imo_number IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
    )
    vessel_name: Mapped[str | None] = mapped_column(Text)
    imo_number: Mapped[str | None] = mapped_column(Text)
    mmsi_number: Mapped[str | None] = mapped_column(Text)
    vessel_type: Mapped[str | None] = mapped_column(Text)
    flag: Mapped[str | None] = mapped_column(Text)
    tonnage: Mapped[str | None] = mapped_column(Text)
    build_year: Mapped[int | None] = mapped_column(Integer)
    call_sign: Mapped[str | None] = mapped_column(Text)

    entity: Mapped[SanctionedEntity] = relationship(back_populates="vessels")


class EntityAddress(Base):
    __tablename__ = "entity_addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
    )
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)

    entity: Mapped[SanctionedEntity] = relationship(back_populates="addresses")


class EntityIdentifier(Base):
    __tablename__ = "entity_identifiers"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
    )
    id_type: Mapped[str] = mapped_column(Text, nullable=False)
    id_value: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)

    entity: Mapped[SanctionedEntity] = relationship(back_populates="identifiers")


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"
    __table_args__ = (
        UniqueConstraint(
            "from_entity_id",
            "to_entity_id",
            "relationship_type",
            name="uq_entity_relationships_from_to_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    ownership_percentage: Mapped[float | None] = mapped_column(Numeric)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)

    from_entity: Mapped[SanctionedEntity] = relationship(
        back_populates="relationships_from", foreign_keys=[from_entity_id]
    )
    to_entity: Mapped[SanctionedEntity] = relationship(
        back_populates="relationships_to", foreign_keys=[to_entity_id]
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(1024))
    source_document: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    article_reference: Mapped[str | None] = mapped_column(Text)
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column()
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    published_date: Mapped[date | None] = mapped_column(Date)
    ingestion_timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    data_vintage: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)


class IngestionLog(Base):
    __tablename__ = "ingestion_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingestion_type: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    records_processed: Mapped[int | None] = mapped_column(Integer)
    records_added: Mapped[int | None] = mapped_column(Integer)
    records_updated: Mapped[int | None] = mapped_column(Integer)
    records_removed: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    source_vintage: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
