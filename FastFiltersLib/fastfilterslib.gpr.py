from gramps.gen.plug._pluginreg import register, STABLE, GENERAL
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

register(
    GENERAL,
    id="fastfilterslib",
    name=_("Fast Filters Library"),
    description=_(
        "Shared library for SQLiteFastFilters and PostgreSQLFastFilters. "
        "Provides SQL-accelerated filter rule overrides and dialect "
        "compatibility helpers."
    ),
    version="1.0.0",
    gramps_target_version="6.0",
    status=STABLE,
    fname="fastfilterslib_addon.py",
    load_on_reg=True,
    authors=["Doug Blank"],
    authors_email=["doug.blank@gmail.com"],
)
