// Resumen del diario de decisiones. Solo suma lo que calculó el job: aquí no se estima nada.

export type JournalLike = {
	open: boolean;
	paid: number | null;
	pnl: number | null;
	vs_baseline: number | null;
	points: number;
	points_aligned: number | null;
	weeks_known_lineup: number;
	entry_kind: string;
	rec_at_entry: string | null;
	rec_at_exit: string | null;
	exit_kind: string | null;
};

export function journalSummary(entries: JournalLike[]) {
	const withPnl = entries.filter((e) => e.pnl != null);
	const sum = (l: JournalLike[], f: (e: JournalLike) => number) => l.reduce((a, e) => a + f(e), 0);
	const closed = withPnl.filter((e) => !e.open);
	const open = withPnl.filter((e) => e.open);
	// En euros: lo que ganaste de más (o de menos) frente a comprar a un jugador típico de su
	// posición con el mismo dinero y en las mismas fechas.
	const vsBase = entries.filter((e) => e.vs_baseline != null && e.paid != null);
	const buys = entries.filter((e) => e.entry_kind !== 'inicial' && e.rec_at_entry);
	const sells = entries.filter((e) => e.exit_kind && e.exit_kind !== 'me_clausularon' && e.rec_at_exit);
	return {
		operations: entries.filter((e) => e.entry_kind !== 'inicial').length,
		realized: sum(closed, (e) => e.pnl!),
		closedCount: closed.length,
		unrealized: sum(open, (e) => e.pnl!),
		openCount: open.length,
		vsBaseline: vsBase.length ? sum(vsBase, (e) => e.vs_baseline! * e.paid!) : null,
		vsBaselineCount: vsBase.length,
		points: sum(entries, (e) => e.points),
		pointsAligned: entries.some((e) => e.points_aligned != null) ? sum(entries, (e) => e.points_aligned ?? 0) : null,
		buysWithRec: buys.length,
		buysRecommended: buys.filter((e) => e.rec_at_entry === 'pujar').length,
		sellsWithRec: sells.length,
		sellsRecommended: sells.filter((e) => e.rec_at_exit === 'vender').length
	};
}
