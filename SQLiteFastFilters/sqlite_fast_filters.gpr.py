from gramps.gen.plug._pluginreg import register, STABLE, DATABASE
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

register(
    DATABASE,
    id="sqlite-fast-filters",
    name=_("SQLite with Fast Filters"),
    name_accell=_("_SQLite with Fast Filters Database"),
    description=_("SQLite database with SQL-accelerated filter overloads"),
    version="1.0.0",
    gramps_target_version="6.0",
    status=STABLE,
    fname="sqlite_fast_filters.py",
    databaseclass="SQLiteFastFilters",
    authors=["Doug Blank"],
    authors_email=["doug.blank@gmail.com"],
    depends_on=["fastfilterslib"],
)
