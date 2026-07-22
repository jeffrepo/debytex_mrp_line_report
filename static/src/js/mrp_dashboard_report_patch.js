/** @odoo-module **/

import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

const MrpDashboard = registry.category("actions").get("mrp_dashboard_tag");

patch(MrpDashboard.prototype, {
    setup() {
        super.setup(...arguments);
        const actionService = useService("action");

        this.state.lineReportLoading = false;
        this.state.lineReportPrinting = false;
        this.state.lineReportError = "";
        this.state.selectedLineReport = null;
        this._lineReportRequestToken = 0;

        const originalOpenDetail = this.openDetail;
        const originalCloseDetail = this.closeDetailModal;

        this.openDetail = async (production) => {
            originalOpenDetail(production);
            const requestToken = ++this._lineReportRequestToken;
            this.state.lineReportLoading = true;
            this.state.lineReportError = "";
            this.state.selectedLineReport = null;

            try {
                const detail = await this.orm.call(
                    "mrp.production",
                    "get_line_report_dashboard_detail",
                    [production.id]
                );
                if (
                    requestToken === this._lineReportRequestToken &&
                    this.state.selectedDetail?.id === production.id
                ) {
                    this.state.selectedLineReport = detail;
                }
            } catch (error) {
                console.error("Error al cargar el reporte de línea:", error);
                if (
                    requestToken === this._lineReportRequestToken &&
                    this.state.selectedDetail?.id === production.id
                ) {
                    this.state.lineReportError =
                        error?.data?.message ||
                        error?.message ||
                        "No fue posible cargar el detalle del reporte.";
                }
                this.notification.add(
                    "No fue posible cargar el reporte completo de la línea",
                    { type: "danger" }
                );
            } finally {
                if (
                    requestToken === this._lineReportRequestToken &&
                    this.state.selectedDetail?.id === production.id
                ) {
                    this.state.lineReportLoading = false;
                }
            }
        };

        this.closeDetailModal = () => {
            this._lineReportRequestToken++;
            originalCloseDetail();
            this.state.lineReportLoading = false;
            this.state.lineReportError = "";
            this.state.selectedLineReport = null;
        };

        this.printLineReport = async () => {
            const production = this.state.selectedDetail;
            const report = this.state.selectedLineReport;
            if (!production || !report || this.state.lineReportPrinting) {
                return;
            }

            this.state.lineReportPrinting = true;
            try {
                const action = await this.orm.call(
                    "mrp.production",
                    "action_print_line_report_from_dashboard",
                    [production.id, report.report_line_id || false]
                );
                await actionService.doAction(action);
            } catch (error) {
                console.error("Error al generar el PDF del reporte de línea:", error);
                this.notification.add(
                    error?.data?.message ||
                        error?.message ||
                        "No fue posible generar el PDF de la orden.",
                    { type: "danger" }
                );
            } finally {
                this.state.lineReportPrinting = false;
            }
        };

        this.displayLineReportValue = (value, suffix = "", digits = null) => {
            if (value === false || value === null || value === undefined || value === "") {
                return "—";
            }
            const displayValue =
                typeof value === "number" && digits !== null
                    ? value.toFixed(digits)
                    : value;
            return `${displayValue}${suffix}`;
        };

        this.displayOptionalLineReportValue = (value, suffix = "", digits = null) => {
            if (value === 0) {
                return "—";
            }
            return this.displayLineReportValue(value, suffix, digits);
        };
    },
});
