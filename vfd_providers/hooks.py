from . import __version__ as app_version

app_name = "vfd_providers"
app_title = "VFD Providers"
app_publisher = "Aakvatech Limited"
app_description = "VFD Providers"
app_email = "info@aakvatech.com"
app_license = "GPL"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/vfd_providers/css/vfd_providers.css"
# app_include_js = "/assets/vfd_providers/js/vfd_providers.js"

# include js, css files in header of web template
# web_include_css = "/assets/vfd_providers/css/vfd_providers.css"
# web_include_js = "/assets/vfd_providers/js/vfd_providers.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "vfd_providers/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
    "Sales Invoice": "utils/sales_invoice.js",
    "Customer": "utils/customer.js",
}

# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "vfd_providers.utils.jinja_methods",
# 	"filters": "vfd_providers.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "vfd_providers.install.before_install"
# after_install = "vfd_providers.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "vfd_providers.uninstall.before_uninstall"
# after_uninstall = "vfd_providers.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "vfd_providers.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }
doc_events = {
    "Sales Invoice": {
        "on_submit": "vfd_providers.utils.utils.autogenerate_vfd",
        "before_cancel": "vfd_providers.utils.sales_invoice.validate_cancel",
        "before_submit": "vfd_providers.utils.sales_invoice.vfd_validation",
    },
    "Customer": {
        "validate": "vfd_providers.utils.utils.clean_and_update_tax_id_info",
    },
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
        "*/10 * * * *": [
            "vfd_providers.vfd_providers.doctype.simplify_vfd_settings.simplify_vfd_settings.get_token"
        ],
    }
}

# Testing
# -------

# before_tests = "vfd_providers.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "vfd_providers.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "vfd_providers.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]


# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"vfd_providers.auth.validate"
# ]
