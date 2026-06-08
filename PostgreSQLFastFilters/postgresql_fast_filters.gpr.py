from gramps.gen.plug._pluginreg import register, STABLE, DATABASE
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

register(
    DATABASE,
    id="postgresql-fast-filters",
    name=_("PostgreSQL with Fast Filters"),
    name_accell=_("_PostgreSQL with Fast Filters Database"),
    description=_("PostgreSQL database with SQL-accelerated filter overloads"),
    version="1.0.0",
    gramps_target_version="6.0",
    status=STABLE,
    fname="postgresql_fast_filters.py",
    databaseclass="PostgreSQLFastFilters",
    authors=["Doug Blank"],
    authors_email=["doug.blank@gmail.com"],
    requires_mod=["psycopg2"],
    depends_on=["fastfilterslib"],
)
