/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useState,
} from "@odoo/owl";


export class DebytexShiftTimerField extends Component {
    static template = "debytex_mrp_line_report.ShiftTimerField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            baseSeconds: this._fieldSeconds(this.props),
            state: this._recordState(this.props),
            sampledAt: Date.now(),
            now: Date.now(),
        });
        this.tickInterval = null;
        this.refreshInterval = null;

        onWillStart(async () => {
            await this._refreshFromServer();
            this.tickInterval = setInterval(() => {
                this.state.now = Date.now();
            }, 1000);
            this.refreshInterval = setInterval(() => {
                this._refreshFromServer();
            }, 5000);
        });
        onWillUpdateProps((nextProps) => {
            const nextSeconds = this._fieldSeconds(nextProps);
            const nextState = this._recordState(nextProps);
            if (
                nextSeconds !== this._fieldSeconds(this.props) ||
                nextState !== this._recordState(this.props)
            ) {
                this._setSample(nextSeconds, nextState);
            }
        });
        onWillUnmount(() => {
            clearInterval(this.tickInterval);
            clearInterval(this.refreshInterval);
        });
    }

    get elapsedSeconds() {
        const liveSeconds = this.state.state === "running"
            ? Math.floor((this.state.now - this.state.sampledAt) / 1000)
            : 0;
        return Math.max(Math.floor(this.state.baseSeconds + liveSeconds), 0);
    }

    get formattedValue() {
        const total = this.elapsedSeconds;
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const seconds = total % 60;
        return [hours, minutes, seconds]
            .map((value) => String(value).padStart(2, "0"))
            .join(":");
    }

    get stateClass() {
        return `debytex-shift-timer-${this.state.state || "closed"}`;
    }

    _fieldSeconds(props) {
        return Number(props.record.data[props.name] || 0);
    }

    _recordState(props) {
        return props.record.data.line_report_active_shift_state || "closed";
    }

    _setSample(seconds, state) {
        const now = Date.now();
        this.state.baseSeconds = Number(seconds || 0);
        this.state.state = state || "closed";
        this.state.sampledAt = now;
        this.state.now = now;
    }

    async _refreshFromServer() {
        const resId = this.props.record.resId;
        if (!resId || this.props.record.resModel !== "mrp.production") {
            return;
        }
        try {
            const timer = await this.orm.call(
                "mrp.production",
                "get_line_report_shift_timer",
                [[resId]]
            );
            this._setSample(timer.seconds, timer.state);
        } catch {
            // The local timer remains usable during a temporary RPC failure.
        }
    }
}


registry.category("fields").add("debytex_shift_timer", {
    component: DebytexShiftTimerField,
    supportedTypes: ["float", "integer"],
});
