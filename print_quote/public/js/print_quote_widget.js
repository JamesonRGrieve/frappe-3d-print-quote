// SPDX-License-Identifier: AGPL-3.0-or-later
// 3D-print quote widget. A page embeds:
//   <div data-print-quote-profile="<Print Quote Profile>"></div>
//   <script src="/assets/print_quote/js/print_quote_widget.js"></script>
// It renders an accessible upload form, posts to print_quote.api.submit and shows the estimate.
(() => {
	const API = "/api/method/print_quote.api.";

	const el = (tag, attrs = {}, children = []) => {
		const node = document.createElement(tag);
		for (const [k, v] of Object.entries(attrs)) {
			if (k === "text") node.textContent = v;
			else node.setAttribute(k, v);
		}
		for (const child of children) node.append(child);
		return node;
	};
	const field = (id, label, input) =>
		el("p", {}, [el("label", { for: id, text: label }), el("br"), Object.assign(input, { id })]);
	const money = (amount, currency) =>
		new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "CAD" }).format(amount);

	async function mount(root) {
		const profile = root.dataset.printQuoteProfile;
		const response = await fetch(`${API}get_profile?profile=${encodeURIComponent(profile)}`);
		if (!response.ok) {
			root.append(el("p", { text: "Quotes are not available right now." }));
			return;
		}
		const config = (await response.json()).message;
		const status = el("p", { role: "status", "aria-live": "polite" });
		const parts = el("div");
		let index = 0;

		const addPart = () => {
			const i = index++;
			const material = el("select", { name: `material_${i}`, required: "" });
			const colour = el("select", { name: `colour_${i}` });
			const fillColours = () => {
				const m = config.materials.find((x) => x.name === material.value);
				colour.replaceChildren(el("option", { value: "", text: "Any / not sure" }),
					...(m ? m.colours : []).map((c) => el("option", { value: c, text: c })));
			};
			config.materials.forEach((m) => material.append(el("option", { value: m.name, text: `${m.name} (${m.process})` })));
			material.addEventListener("change", fillColours);
			fillColours();
			const set = el("fieldset", { "data-part": String(i) }, [
				el("legend", { text: `Part ${i + 1}` }),
				field(`file_${i}`, "Model file (STL or 3MF)", el("input", { type: "file", name: `file_${i}`,
					accept: config.accept.join(","), required: "" })),
				field(`material_${i}`, "Material", material),
				field(`colour_${i}`, "Colour", colour),
				field(`quantity_${i}`, "Quantity", el("input", { type: "number", name: `quantity_${i}`, min: "1",
					max: String(config.max_quantity), value: "1", required: "" })),
			]);
			parts.append(set);
			addButton.disabled = index >= config.max_files;
		};

		const addButton = el("button", { type: "button", text: "Add another part" });
		addButton.addEventListener("click", addPart);
		const form = el("form", { novalidate: "" }, [
			parts, el("p", {}, [addButton]),
			field("pq_name", "Your name", el("input", { name: "contact_name", required: "", autocomplete: "name" })),
			field("pq_email", "Email", el("input", { name: "email", type: "email", required: "", autocomplete: "email" })),
			field("pq_phone", "Phone (optional)", el("input", { name: "phone", type: "tel", autocomplete: "tel" })),
			field("pq_org", "Organization (optional)", el("input", { name: "organization", autocomplete: "organization" })),
			field("pq_notes", "Requirements (strength, finish, deadline)", el("textarea", { name: "notes", rows: "3" })),
			el("p", {}, [el("button", { type: "submit", class: "btn", text: "Get my quote" })]),
			status,
		]);
		root.append(form);
		addPart();

		form.addEventListener("submit", async (event) => {
			event.preventDefault();
			if (!form.reportValidity()) return;
			const data = new FormData();
			data.append("profile", profile);
			for (const name of ["contact_name", "email", "phone", "organization", "notes"]) data.append(name, form.elements[name].value);
			const list = [...parts.querySelectorAll("fieldset")].map((set) => {
				const i = set.dataset.part;
				data.append(`file_${i}`, form.elements[`file_${i}`].files[0]);
				return { field: `file_${i}`, material: form.elements[`material_${i}`].value,
					colour: form.elements[`colour_${i}`].value, quantity: form.elements[`quantity_${i}`].value };
			});
			data.append("parts", JSON.stringify(list));
			status.textContent = "Analysing your models…";
			const result = await fetch(`${API}submit`, { method: "POST", body: data, headers: { Accept: "application/json" } });
			const body = await result.json().catch(() => ({}));
			if (!result.ok) {
				const messages = body._server_messages ? JSON.parse(body._server_messages).map((m) => JSON.parse(m).message) : [];
				status.textContent = messages.join(" ") || "We couldn't quote these files. Please check them and try again.";
				return;
			}
			const q = body.message;
			form.replaceChildren(
				el("h2", { text: `Estimated total: ${money(q.estimated_total, q.currency)}` }),
				el("ul", {}, q.parts.map((p) => el("li", { text: `${p.file}: ${p.quantity} × ${p.material}, ~${p.grams} g (${p.size_mm.join(" × ")} mm)` }))),
				el("p", { text: q.review
					? `Thanks! We'll confirm the price and lead time by email (reference ${q.request}).`
					: `Your quote has been sent to your email (reference ${q.request}).` }),
				status,
			);
			status.textContent = "Estimate ready.";
		});
	}

	document.querySelectorAll("[data-print-quote-profile]").forEach((root) => mount(root));
})();
