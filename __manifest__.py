{
    "name": "Debytex - Reporte de Producción por Línea",
    "version": "18.0.1.5.2",
    "category": "Manufacturing/Reporting",
    "summary": "Reporte técnico y general de producción por línea",
    "description": """
        Captura y consolida el estado operativo de las líneas de producción
        de Debytex/ECOWOOL. Genera un reporte técnico por línea y un resumen
        general en PDF usando las órdenes, turnos, rollos y centros de trabajo
        existentes en la operación de fabricación.
    """,
    "author": "Debytex",
    "website": "https://github.com/jeffrepo/debytex_mrp_line_report",
    "license": "LGPL-3",
    "depends": [
        "custom_novici",
        "mrp",
        "mrp_workorder",
        "web",
    ],
    "data": [
        "security/production_line_report_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/mrp_production_parameter_views.xml",
        "views/production_line_report_views.xml",
        "wizard/workcenter_selector_wizard_views.xml",
        "wizard/production_line_report_wizard_views.xml",
        "report/production_line_report_actions.xml",
        "report/production_line_report_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "debytex_mrp_line_report/static/src/xml/mrp_dashboard_report.xml",
            "debytex_mrp_line_report/static/src/xml/mrp_shift_timer_field.xml",
            "debytex_mrp_line_report/static/src/js/mrp_dashboard_report_patch.js",
            "debytex_mrp_line_report/static/src/js/mrp_shift_timer_field.js",
            "debytex_mrp_line_report/static/src/css/mrp_dashboard_report.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
