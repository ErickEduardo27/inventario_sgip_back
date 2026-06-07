"""Tablas de inventario físico (SAP-GrupoISO / Laravel tenant).

Revision ID: 017_inventory_grupo_iso
Revises: 016_scheduled_celery
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "017_inventory_grupo_iso"
down_revision = "016_scheduled_celery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=True),
        sa.Column("identity_document_type_id", sa.String(length=50), nullable=True),
        sa.Column("number", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("trade_name", sa.String(length=500), nullable=True),
        sa.Column("country_id", sa.String(length=50), nullable=True),
        sa.Column("department_id", sa.String(length=50), nullable=True),
        sa.Column("province_id", sa.String(length=50), nullable=True),
        sa.Column("district_id", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("telephone", sa.String(length=100), nullable=True),
        sa.Column("enviroment_code", sa.String(length=100), nullable=True),
        sa.Column("cc_code", sa.String(length=100), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_persons_tenant_id"), "persons", ["tenant_id"])
    op.create_index(op.f("ix_persons_number"), "persons", ["number"])
    op.create_index(op.f("ix_persons_enviroment_code"), "persons", ["enviroment_code"])

    op.create_table(
        "establishments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("country_id", sa.String(length=50), nullable=True),
        sa.Column("department_id", sa.String(length=50), nullable=True),
        sa.Column("province_id", sa.String(length=50), nullable=True),
        sa.Column("district_id", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("telephone", sa.String(length=100), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("trade_address", sa.String(length=500), nullable=True),
        sa.Column("web_address", sa.String(length=500), nullable=True),
        sa.Column("aditional_information", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_establishments_tenant_id"), "establishments", ["tenant_id"])
    op.create_index(op.f("ix_establishments_customer_id"), "establishments", ["customer_id"])

    op.create_table(
        "cost_center",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("personal_id", sa.BigInteger(), nullable=True),
        sa.Column("principal_center_id", sa.BigInteger(), nullable=True),
        sa.Column("user_create", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["personal_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["principal_center_id"], ["establishments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_inv_cost_center_tenant_code"),
    )
    op.create_index(op.f("ix_cost_center_tenant_id"), "cost_center", ["tenant_id"])
    op.create_index(op.f("ix_cost_center_principal_center_id"), "cost_center", ["principal_center_id"])

    op.create_table(
        "enviroments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("establishment_id", sa.BigInteger(), nullable=False),
        sa.Column("floor", sa.String(length=100), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("telephone", sa.String(length=100), nullable=True),
        sa.Column("anex", sa.String(length=100), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("image", sa.String(length=500), nullable=True),
        sa.Column("user_create", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_enviroments_tenant_id"), "enviroments", ["tenant_id"])
    op.create_index(op.f("ix_enviroments_establishment_id"), "enviroments", ["establishment_id"])
    op.create_index(op.f("ix_enviroments_code"), "enviroments", ["code"])

    op.create_table(
        "margesi",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inv_num", sa.String(length=100), nullable=True),
        sa.Column("inv_hoj", sa.String(length=100), nullable=True),
        sa.Column("inv_sit", sa.String(length=50), nullable=True),
        sa.Column("inv_con", sa.String(length=50), nullable=True),
        sa.Column("mar_cpat", sa.String(length=200), nullable=True),
        sa.Column("mar_des", sa.String(length=500), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_margesi_tenant_id"), "margesi", ["tenant_id"])
    op.create_index(op.f("ix_margesi_inv_num"), "margesi", ["inv_num"])
    op.create_index(op.f("ix_margesi_mar_cpat"), "margesi", ["mar_cpat"])

    op.create_table(
        "cards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("hoj_num", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("hoj_fec", sa.Date(), nullable=True),
        sa.Column("hoj_can_tot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id_ambiente", sa.BigInteger(), nullable=False),
        sa.Column("id_ccosto", sa.BigInteger(), nullable=False),
        sa.Column("id_usuario", sa.BigInteger(), nullable=True),
        sa.Column("id_digitador", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id_inventariador", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hoj_c_con", sa.String(length=50), nullable=True),
        sa.Column("hoj_c_sob", sa.String(length=50), nullable=True),
        sa.Column("hoj_e_nue", sa.String(length=50), nullable=True),
        sa.Column("hoj_e_bue", sa.String(length=50), nullable=True),
        sa.Column("hoj_e_reg", sa.String(length=50), nullable=True),
        sa.Column("hoj_e_mal", sa.String(length=50), nullable=True),
        sa.Column("hoj_e_ins", sa.String(length=50), nullable=True),
        sa.Column("hoj_e_rae", sa.String(length=50), nullable=True),
        sa.Column("flag_firma", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("nota_interna", sa.Text(), nullable=True),
        sa.Column("nota_ficha", sa.Text(), nullable=True),
        sa.Column("state", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pdf", sa.String(length=500), nullable=True),
        sa.Column("pdf2", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["id_ambiente"], ["enviroments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["id_ccosto"], ["cost_center.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["id_digitador"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["id_inventariador"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["id_usuario"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cards_tenant_id"), "cards", ["tenant_id"])
    op.create_index(op.f("ix_cards_hoj_num"), "cards", ["hoj_num"])
    op.create_index(op.f("ix_cards_id_ambiente"), "cards", ["id_ambiente"])
    op.create_index(op.f("ix_cards_id_ccosto"), "cards", ["id_ccosto"])
    op.create_index(op.f("ix_cards_id_digitador"), "cards", ["id_digitador"])

    op.create_table(
        "itemcards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id_card", sa.BigInteger(), nullable=False),
        sa.Column("inv_num", sa.String(length=100), nullable=True),
        sa.Column("mar_cpat", sa.String(length=200), nullable=True),
        sa.Column("mar_num", sa.String(length=200), nullable=True),
        sa.Column("mar_des", sa.String(length=500), nullable=True),
        sa.Column("inv_sit", sa.String(length=20), nullable=True),
        sa.Column("inv_con", sa.String(length=20), nullable=True),
        sa.Column("inv_num_1", sa.String(length=100), nullable=True),
        sa.Column("inv_num_2", sa.String(length=100), nullable=True),
        sa.Column("amb_cod_his", sa.String(length=100), nullable=True),
        sa.Column("mar_sit_conta", sa.String(length=100), nullable=True),
        sa.Column("id_margesi", sa.BigInteger(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["id_card"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_margesi"], ["margesi.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_itemcards_tenant_id"), "itemcards", ["tenant_id"])
    op.create_index(op.f("ix_itemcards_id_card"), "itemcards", ["id_card"])
    op.create_index(op.f("ix_itemcards_inv_num"), "itemcards", ["inv_num"])
    op.create_index(op.f("ix_itemcards_mar_cpat"), "itemcards", ["mar_cpat"])
    op.create_index(op.f("ix_itemcards_id_margesi"), "itemcards", ["id_margesi"])

    op.create_table(
        "list_sbn",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("cat_des", sa.String(length=500), nullable=True),
        sa.Column("cat_ulti", sa.String(length=200), nullable=True),
        sa.Column("cat_clase", sa.String(length=200), nullable=True),
        sa.Column("cat_cat", sa.String(length=200), nullable=True),
        sa.Column("cat_cont_vutil", sa.String(length=200), nullable=True),
        sa.Column("cat_cont_pdep", sa.String(length=200), nullable=True),
        sa.Column("cat_cont_gasto", sa.String(length=200), nullable=True),
        sa.Column("cat_cont_cta_a", sa.String(length=200), nullable=True),
        sa.Column("cat_cont_cta_o", sa.String(length=200), nullable=True),
        sa.Column("cat_cont_valp", sa.String(length=200), nullable=True),
        sa.Column("cat_uso", sa.String(length=200), nullable=True),
        sa.Column("cat_raa", sa.String(length=200), nullable=True),
        sa.Column("cat_foto", sa.String(length=500), nullable=True),
        sa.Column("cat_obs", sa.Text(), nullable=True),
        sa.Column("user_create", sa.String(length=200), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_inv_list_sbn_tenant_code"),
    )
    op.create_index(op.f("ix_list_sbn_tenant_id"), "list_sbn", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_list_sbn_tenant_id"), table_name="list_sbn")
    op.drop_table("list_sbn")

    op.drop_index(op.f("ix_itemcards_id_margesi"), table_name="itemcards")
    op.drop_index(op.f("ix_itemcards_mar_cpat"), table_name="itemcards")
    op.drop_index(op.f("ix_itemcards_inv_num"), table_name="itemcards")
    op.drop_index(op.f("ix_itemcards_id_card"), table_name="itemcards")
    op.drop_index(op.f("ix_itemcards_tenant_id"), table_name="itemcards")
    op.drop_table("itemcards")

    op.drop_index(op.f("ix_cards_id_digitador"), table_name="cards")
    op.drop_index(op.f("ix_cards_id_ccosto"), table_name="cards")
    op.drop_index(op.f("ix_cards_id_ambiente"), table_name="cards")
    op.drop_index(op.f("ix_cards_hoj_num"), table_name="cards")
    op.drop_index(op.f("ix_cards_tenant_id"), table_name="cards")
    op.drop_table("cards")

    op.drop_index(op.f("ix_margesi_mar_cpat"), table_name="margesi")
    op.drop_index(op.f("ix_margesi_inv_num"), table_name="margesi")
    op.drop_index(op.f("ix_margesi_tenant_id"), table_name="margesi")
    op.drop_table("margesi")

    op.drop_index(op.f("ix_enviroments_code"), table_name="enviroments")
    op.drop_index(op.f("ix_enviroments_establishment_id"), table_name="enviroments")
    op.drop_index(op.f("ix_enviroments_tenant_id"), table_name="enviroments")
    op.drop_table("enviroments")

    op.drop_index(op.f("ix_cost_center_principal_center_id"), table_name="cost_center")
    op.drop_index(op.f("ix_cost_center_tenant_id"), table_name="cost_center")
    op.drop_table("cost_center")

    op.drop_index(op.f("ix_establishments_customer_id"), table_name="establishments")
    op.drop_index(op.f("ix_establishments_tenant_id"), table_name="establishments")
    op.drop_table("establishments")

    op.drop_index(op.f("ix_persons_enviroment_code"), table_name="persons")
    op.drop_index(op.f("ix_persons_number"), table_name="persons")
    op.drop_index(op.f("ix_persons_tenant_id"), table_name="persons")
    op.drop_table("persons")
