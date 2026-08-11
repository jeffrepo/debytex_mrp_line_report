/** @odoo-module **/

import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

const MrpDashboard = registry.category("actions").get("mrp_dashboard_tag");
const SUMMARY_CARD_SELECTOR = ".debytex-order-summary-card";
const FOUR_LINE_GRID_CLASS = "debytex-four-line-grid";

function findCommonAncestor(elements) {
    if (!elements.length) {
        return null;
    }

    let candidate = elements[0].parentElement;
    while (candidate && !elements.every((element) => candidate.contains(element))) {
        candidate = candidate.parentElement;
    }
    return candidate;
}

function findLineGrid(cards) {
    const commonAncestor = findCommonAncestor(cards);
    if (!commonAncestor) {
        return null;
    }

    const columnsWithOrders = [...commonAncestor.children].filter((child) =>
        child.querySelector(SUMMARY_CARD_SELECTOR)
    );
    return columnsWithOrders.length >= 4 ? commonAncestor : null;
}

patch(MrpDashboard.prototype, {
    setup() {
        super.setup(...arguments);
        const actionService = useService("action");

        this.state.lineReportLoading = false;
        this.state.lineReportPrinting = false;
        this.state.lineReportError = "";
        this.state.selectedLineReport = null;
        this._lineReportRequestToken = 0;
        this._debytexLineGrid = null;

        this._updateFourLineLayout = () => {
            const cards = [...document.querySelectorAll(SUMMARY_CARD_SELECTOR)];
            const lineGrid = findLineGrid(cards);

            if (this._debytexLineGrid && this._debytexLineGrid !== lineGrid) {
                this._debytexLineGrid.classList.remove(FOUR_LINE_GRID_CLASS);
            }
            if (lineGrid) {
                lineGrid.classList.add(FOUR_LINE_GRID_CLASS);
            }
            this._debytexLineGrid = lineGrid;
        };

        onMounted(this._updateFourLineLayout);
        onPatched(this._updateFourLineLayout);
        onWillUnmount(() => {
            this._debytexLineGrid?.classList.remove(FOUR_LINE_GRID_CLASS);
            this._debytexLineGrid = null;
        });

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
