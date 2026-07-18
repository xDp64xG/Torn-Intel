from datetime import datetime

from utils.colors import header, info, success, warning, muted, highlight


class ReviveReport:

    def __init__(self, queries, logger):
        self.queries = queries
        self.logger = logger

    #########################################################

    def requests_list(self, status="pending", target_name=None, limit=50):

        rows = self.queries.revive_requests(status=status, target_name=target_name, limit=limit)

        lines = []
        lines.append(f"\n{header('========== REVIVE REQUESTS ==========')}")
        lines.append(f"Status filter: {info(status)} | Rows: {info(str(len(rows)))}")

        if target_name:
            lines.append(f"Target filter: {highlight(target_name)}")

        if not rows:
            lines.append(muted("- no revive requests found"))
            lines.append(header("====================================\n"))
            return "\n".join(lines)

        for row in rows:
            requested_at = int(row.get("requested_timestamp") or 0)
            requested_text = datetime.fromtimestamp(requested_at).strftime("%m-%d %H:%M") if requested_at else "-"
            state = str(row.get("status") or "pending").lower()
            state_text = success(state) if state == "fulfilled" else warning(state)
            target = highlight(row.get("target_name") or f"Target {row.get('target_id')}")
            requester = info(row.get("requester_name") or f"Requester {row.get('requester_id') or '-'}")

            line = f"- {requested_text} | {target} | requested by {requester} | {state_text}"

            if state == "fulfilled":
                revived_at = int(row.get("revived_timestamp") or 0)
                revived_text = datetime.fromtimestamp(revived_at).strftime("%m-%d %H:%M") if revived_at else "-"
                fulfilled_by = success(row.get('fulfilled_by_name') or row.get('fulfilled_by_id'))
                line += (
                    f" | revived by {fulfilled_by}"
                    f" | revived at {success(revived_text)}"
                    f" | revive_id {muted(row.get('fulfilled_revive_id'))}"
                )

            lines.append(line)

        lines.append(header("====================================\n"))
        return "\n".join(lines)