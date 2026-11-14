class Menu:
    def __init__(self, label, link = "javascript:void(0)", css_icon = 'fa fa-caret-right fa-fw', submenu = [], admin_only = False):
        """
        Create a menu
        :param label: text shown in entry
        :param css_icon: class used for showing an icon (for example, "fa fa-wrench")
        :param link: link of entry (use "#" or "javascript:void(0);" for no action)
        :param submenu: list of Menu items
        :param admin_only: show only to superusers
        """
        super().__init__()

        self.label = label
        self.css_icon = css_icon
        self.link = link
        self.submenu = submenu
        self.admin_only = admin_only

        if (self.has_submenu()):
            self.link = "#"


    def has_submenu(self):
        return len(self.submenu) > 0
