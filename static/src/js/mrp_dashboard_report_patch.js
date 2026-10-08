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
        this.state.dashboardSequenceOrders = [];
        this.state.dashboardSequencePosition = "1";
        this.state.dashboardSequenceLoading = false;
        this.state.dashboardSequenceSaving = false;
        this.state.dashboardTimerNow = Date.now();
        this._lineReportRequestToken = 0;
        this._dashboardSequenceRequestToken = 0;
        this._dashboardTimerSamples = new Map();
        this._dashboardTimerInterval = null;
        this._debytexLineGrid = null;

        const originalOpenPriorityModal = this.openPriorityModal;
        const originalClosePriorityModal = this.closePriorityModal;

        this.openPriorityModal = () => {
            this.state.selectedWorkcenter = null;
            this.state.selectedOrder = null;
            this.state.dashboardSequenceOrders = [];
            this.state.dashboardSequencePosition = "1";
            originalOpenPriorityModal();
        };

        this.closePriorityModal = () => {
            this._dashboardSequenceRequestToken++;
            originalClosePriorityModal();
            this.state.dashboardSequenceOrders = [];
            this.state.dashboardSequenceLoading = false;
            this.state.dashboardSequenceSaving = false;
        };

        this.loadDashboardSequenceOrders = async (workcenterId) => {
            const requestToken = ++this._dashboardSequenceRequestToken;
            if (!workcenterId) {
                this.state.dashboardSequenceOrders = [];
                return;
            }
            this.state.dashboardSequenceLoading = true;
            try {
                const orders = await this.orm.call(
                    "mrp.production",
                    "get_dashboard_sequence_options",
                    [Number(workcenterId)]
                );
                if (requestToken === this._dashboardSequenceRequestToken) {
                    this.state.dashboardSequenceOrders = orders;
                }
            } catch (error) {
                console.error("Error al cargar la secuencia del tablero:", error);
                this.notification.add(
                    "No fue posible cargar las órdenes del centro",
                    { type: "danger" }
                );
            } finally {
                if (requestToken === this._dashboardSequenceRequestToken) {
                    this.state.dashboardSequenceLoading = false;
                }
            }
        };

        this.onDashboardSequenceWorkcenterChange = async (event) => {
            this.state.selectedWorkcenter = event.target.value;
            this.state.selectedOrder = null;
            this.state.dashboardSequencePosition = "1";
            await this.loadDashboardSequenceOrders(event.target.value);
        };

        this.onDashboardSequenceOrderChange = (event) => {
            this.state.selectedOrder = event.target.value;
            const selectedOrder = this.state.dashboardSequenceOrders.find(
                (order) => order.id === Number(event.target.value)
            );
            this.state.dashboardSequencePosition = String(
                selectedOrder?.position || 1
            );
        };

        this.saveDashboardSequence = async () => {
            if (
                !this.state.selectedWorkcenter ||
                !this.state.selectedOrder ||
                this.state.dashboardSequenceSaving
            ) {
                this.notification.add(
                    "Seleccione el centro y la orden que desea acomodar",
                    { type: "warning" }
                );
                return;
            }
            this.state.dashboardSequenceSaving = true;
            try {
                const result = await this.orm.call(
                    "mrp.production",
                    "update_dashboard_sequence",
                    [
                        Number(this.state.selectedWorkcenter),
                        Number(this.state.selectedOrder),
                        Number(this.state.dashboardSequencePosition),
                    ]
                );
                if (!result?.success) {
                    this.notification.add(
                        result?.message || "No fue posible guardar el orden",
                        { type: "danger" }
                    );
                    return;
                }
                const data = await this.orm.call(
                    "mrp.production",
                    "get_dashboard_data",
                    []
                );
                this.state.workcenters = Object.values(data);
                this.state.last_update = new Date().toLocaleTimeString();
                this.notification.add(result.message, { type: "success" });
                this.closePriorityModal();
            } catch (error) {
                console.error("Error al guardar la secuencia del tablero:", error);
                this.notification.add(
                    error?.data?.message ||
                        error?.message ||
                        "No fue posible guardar el orden",
                    { type: "danger" }
                );
            } finally {
                this.state.dashboardSequenceSaving = false;
            }
        };

        this.formatDashboardEffectiveTime = (production, summary) => {
            if (!summary?.effective_time_available) {
                return "—";
            }
            const productionId = Number(production.id);
            const baseSeconds = Math.max(
                Math.floor(Number(summary.effective_time_seconds || 0)),
                0
            );
            const timerState = summary.effective_time_state || "closed";
            const shiftId = Number(summary.effective_time_shift_id || 0);
            let sample = this._dashboardTimerSamples.get(productionId);
            if (
                !sample ||
                sample.baseSeconds !== baseSeconds ||
                sample.timerState !== timerState ||
                sample.shiftId !== shiftId
            ) {
                sample = {
                    baseSeconds,
                    timerState,
                    shiftId,
                    sampledAt: this.state.dashboardTimerNow,
                };
                this._dashboardTimerSamples.set(productionId, sample);
            }
            const liveSeconds = timerState === "running"
                ? Math.floor(
                    (this.state.dashboardTimerNow - sample.sampledAt) / 1000
                )
                : 0;
            const totalSeconds = Math.max(baseSeconds + liveSeconds, 0);
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = totalSeconds % 60;
            return [hours, minutes, seconds]
                .map((value) => String(value).padStart(2, "0"))
                .join(":");
        };

        this.dashboardEffectiveTimerIcon = (summary) => {
            if (summary?.effective_time_state === "paused") {
                return "fa-pause-circle";
            }
            if (summary?.effective_time_state === "running") {
                return "fa-clock-o";
            }
            return "fa-stop-circle";
        };

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

        onMounted(() => {
            this._updateFourLineLayout();
            this._dashboardTimerInterval = setInterval(() => {
                this.state.dashboardTimerNow = Date.now();
            }, 1000);
        });
        onPatched(this._updateFourLineLayout);
        onWillUnmount(() => {
            clearInterval(this._dashboardTimerInterval);
            this._dashboardTimerSamples.clear();
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
