#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2024  Gramps Development Team
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.
#
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

MODULE_VERSION = "6.0"

register(
    ASSISTPANEL,
    id="grampsassist",
    name=_("Gramps Assistant"),
    description=_("AI assistant panel for querying your Gramps family tree"),
    version="1.0.0",
    gramps_target_version=MODULE_VERSION,
    status=STABLE,
    fname="grampsassist.py",
    authors=["Douglas S. Blank"],
    authors_email=["dsblank@gmail.com"],
    assistpanelclass="GrampsAssist",
    panel_label=_("Gramps Assistant"),
    order=END,
)
