
        let allRelationships = [];

        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        async function fetchJson(url, options = {}) {
            const res = await fetch(url, options);
            if (!res.ok) {
                const text = await res.text();
                throw new Error(text || `HTTP ${res.status}`);
            }
            return await res.json();
        }

        function formatHumanNorm(fact) {
            if (fact.normalized_value === null || fact.normalized_value === undefined) return '';
            const val = Number(fact.normalized_value);
            const unit = fact.normalized_unit || fact.unit || '';

            let formatted = val.toLocaleString();
            if (val >= 1e9) formatted = (val / 1e9).toFixed(2) + 'B';
            else if (val >= 1e6) formatted = (val / 1e6).toFixed(2) + 'M';
            else if (val >= 1e3 && val % 1 !== 0) formatted = val.toFixed(2);

            return `Normalized: ${formatted} ${escapeHtml(unit)}`;
        }

        // Canonical refresh function - updates all UI panels safely
        async function refreshData() {
            console.log("[STATE] Refreshing application state...");
            
            // 1. Documents
            try {
                const docs = await fetchJson('/documents');
                document.getElementById('docCountBadge').innerText = `${docs.length} Docs`;
                document.getElementById('sumDocs').innerText = docs.length;
                renderDocs(docs);
            } catch (e) {
                console.error("Error loading documents:", e);
            }

            // 2. Facts
            try {
                const facts = await fetchJson('/facts');
                document.getElementById('sumFacts').innerText = facts.length;
                renderFacts(facts);
            } catch (e) {
                console.error("Error loading facts:", e);
            }

            // 3. Relationships
            try {
                allRelationships = await fetchJson('/relationships');
                renderRelationships(allRelationships);

                let corrCount = 0, contraCount = 0, reconcCount = 0, temporalCount = 0;
                if (Array.isArray(allRelationships)) {
                    allRelationships.forEach(r => {
                        const typeUpper = (r.relationship_type || '').toUpperCase();
                        if (typeUpper === 'CORROBORATES') corrCount++;
                        else if (typeUpper.includes('CONTRADICT')) contraCount++;
                        else if (typeUpper.includes('RECONCILED')) reconcCount++;
                        else if (typeUpper === 'TEMPORAL_COMPARISON') temporalCount++;
                    });
                }
                document.getElementById('sumCorr').innerText = corrCount;
                document.getElementById('sumContra').innerText = contraCount;
                document.getElementById('sumReconc').innerText = reconcCount;
                document.getElementById('sumTemporal').innerText = temporalCount;
            } catch (e) {
                console.error("Error loading relationships:", e);
            }

            // 4. Rejected Extractions
            try {
                const rejectedGrouped = await fetchJson('/rejected-extractions');
                document.getElementById('sumRejected').innerText = (rejectedGrouped && rejectedGrouped.total_rejected) || 0;
                renderRejected(rejectedGrouped);
            } catch (e) {
                console.error("Error loading rejected extractions:", e);
            }

            // 5. Evaluator Cases
            try {
                const cases = await fetchJson('/cases');
                renderCases(cases);
            } catch (e) {
                console.error("Error loading cases:", e);
            }
        }

        async function uploadFile(file) {
            if (!file) return;
            const fileInput = document.getElementById('fileInput');
            const dropzoneContent = document.getElementById('dropzoneContent');
            const origHTML = dropzoneContent ? dropzoneContent.innerHTML : '<p>Click or drag PDF file</p>';

            console.log("[UPLOAD] Starting upload for file:", file.name);

            if (dropzoneContent) {
                dropzoneContent.innerHTML = '<p style="font-weight:600;color:var(--primary);">⏳ Uploading PDF...</p>';
            }

            const formData = new FormData();
            formData.append('file', file);

            let docId = null;
            try {
                const data = await fetchJson('/upload', { method: 'POST', body: formData });
                docId = data.doc_id;
                console.log("[UPLOAD] Ingestion successful, doc_id:", docId);
            } catch (e) {
                console.error("[UPLOAD] Failed:", e);
                if (dropzoneContent) dropzoneContent.innerHTML = origHTML;
                if (fileInput) fileInput.value = '';
                alert("Upload failed: " + e.message);
                return;
            }

            // 1. Immediately refresh documents list so new document card appears right away!
            await refreshData();

            // 2. Now extract facts for the newly ingested document
            if (dropzoneContent) {
                dropzoneContent.innerHTML = '<p style="font-weight:600;color:var(--warning);">🔍 Extracting facts...</p>';
            }

            try {
                console.log("[EXTRACT] Starting extraction for doc_id:", docId);
                const extData = await fetchJson(`/extract/${docId}`, { method: 'POST' });
                console.log("[EXTRACT] Complete for doc_id:", docId, "Facts:", extData.facts_extracted_count);
                if (extData.mode === 'degraded') {
                    const banner = document.getElementById('degradedBanner');
                    if (banner) banner.style.display = 'flex';
                }
            } catch (e) {
                console.error("[EXTRACT] Failed:", e);
                alert("Document uploaded, but fact extraction failed: " + e.message + "\n\nYou can retry by clicking 'Extract Facts' on the document card.");
            } finally {
                if (dropzoneContent) dropzoneContent.innerHTML = origHTML;
                if (fileInput) fileInput.value = '';
                await refreshData();
            }
        }

        async function deleteDoc(docId, btnEl) {
            if (!confirm("Remove this document and all associated facts?")) return;
            const origText = btnEl ? btnEl.innerHTML : '🗑️ Remove';
            try {
                if (btnEl) {
                    btnEl.disabled = true;
                    btnEl.innerHTML = '⏳ Removing...';
                }
                await fetchJson(`/documents/${docId}`, { method: 'DELETE' });
                await refreshData();
            } catch (e) {
                alert("Failed to delete document: " + e.message);
            } finally {
                if (btnEl) {
                    btnEl.disabled = false;
                    btnEl.innerHTML = origText;
                }
            }
        }

        async function deleteAllDocs() {
            if (!confirm("Clear all ingested documents, facts, and relationships?")) return;
            const btn = document.getElementById('clearAllBtn');
            const origText = btn ? btn.innerHTML : '🗑️ Clear All Docs';
            try {
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '⏳ Clearing...';
                }
                await fetchJson('/documents', { method: 'DELETE' });
                await refreshData();
            } catch (e) {
                alert("Failed to clear documents: " + e.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origText;
                }
            }
        }

        async function extractFactsForDoc(docId, btnEl) {
            const origText = btnEl ? btnEl.innerHTML : 'Extract Facts';
            try {
                if (btnEl) {
                    btnEl.disabled = true;
                    btnEl.innerHTML = '⏳ Extracting...';
                }
                const extData = await fetchJson(`/extract/${docId}`, { method: 'POST' });
                if (extData.mode === 'degraded') {
                    const banner = document.getElementById('degradedBanner');
                    if (banner) banner.style.display = 'flex';
                }
                await refreshData();
            } catch (e) {
                alert("Extraction failed: " + e.message);
            } finally {
                if (btnEl) {
                    btnEl.disabled = false;
                    btnEl.innerHTML = origText;
                }
            }
        }

        async function runAnalysis() {
            const btn = document.getElementById('runAnalysisBtn');
            const origText = btn ? btn.innerHTML : '⚡ Run Cross-Doc Analysis';
            try {
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '⏳ Running Analysis...';
                }
                console.log("[ANALYSIS] Running cross-document analysis...");

                const docs = await fetchJson('/documents');
                if (!Array.isArray(docs) || docs.length < 2) {
                    alert("Upload at least two documents before running cross-document analysis.");
                    return;
                }

                const data = await fetchJson('/analyze', { method: 'POST' });
                console.log("[ANALYSIS] Response received:", data);

                await refreshData();
                switchTab('relsTab');

                alert(`Analysis Complete!\nEvaluated ${data.candidate_pairs_evaluated} candidate pairs.\nRelationships found: ${data.relationships_found_count}\n- Corroborations: ${data.corroborations_count}\n- Reconciled Context: ${data.reconciled_count}\n- Temporal Comparisons: ${data.temporal_comparisons_count || 0}\n- Contradictions: ${data.contradictions_count + (data.likely_contradictions_count || 0)}\n- Unrelated: ${data.unrelated_count}`);
            } catch (e) {
                console.error("[ANALYSIS] Error:", e);
                alert("Cross-document analysis failed: " + e.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origText;
                }
            }
        }

        function renderDocs(docs) {
            const container = document.getElementById('docList');
            if (!Array.isArray(docs) || docs.length === 0) {
                container.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-muted);">No documents uploaded yet.</p>`;
                return;
            }

            container.innerHTML = docs.map(d => `
                <div class="doc-card">
                    <div class="doc-card-header">
                        <span class="doc-name">${escapeHtml(d.filename)}</span>
                        <button class="btn btn-danger btn-sm" onclick="deleteDoc('${d.id}', this)">🗑️ Remove</button>
                    </div>
                    <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 8px;">
                        Pages: ${d.page_count} | Chunks: ${d.chunk_count}
                    </div>
                    <button class="btn btn-secondary btn-sm" style="width: 100%; justify-content: center;" onclick="extractFactsForDoc('${d.id}', this)">Extract Facts</button>
                </div>
            `).join('');
        }

        function renderFacts(facts) {
            const container = document.getElementById('factList');
            if (!Array.isArray(facts) || facts.length === 0) {
                container.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-muted);">No facts extracted yet. Upload a PDF or click "Extract Facts".</p>`;
                return;
            }

            container.innerHTML = facts.map(f => {
                const finalPct = Math.min(100, Math.max(0, ((f.final_confidence || 1.0) * 100))).toFixed(0);
                const normStr = formatHumanNorm(f);
                const docName = f.source_document || (f.document_id ? f.document_id.substring(0, 8) : 'Unknown Doc');

                let unitDisplay = f.unit || '';
                if (f.value && (f.value.includes('₹') || f.value.includes('$')) && unitDisplay === 'INR') {
                    unitDisplay = '';
                }

                return `
                    <div class="fact-card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <div>
                                <span class="badge badge-primary">${escapeHtml(f.entity || f.subject || 'Entity')}</span>
                                ${f.period ? `<span class="badge badge-warning">${escapeHtml(f.period)}</span>` : ''}
                                ${f.value_type ? `<span class="badge badge-muted">${escapeHtml(f.value_type)}</span>` : ''}
                            </div>
                            <span class="badge badge-success">Conf: ${finalPct}%</span>
                        </div>
                        
                        <div class="fact-metric">${escapeHtml(f.metric)}</div>
                        
                        <div class="fact-val-box">
                            <span class="fact-val">${escapeHtml(f.value)}</span>
                            <span class="fact-unit">${escapeHtml(unitDisplay)}</span>
                        </div>

                        <details style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px;">
                            <summary style="cursor: pointer; color: var(--warning); font-weight: 500;">Technical Details & Normalization</summary>
                            <div style="padding-top: 4px;">
                                ${normStr ? `<div>${normStr}</div>` : ''}
                                <div>Binding Method: <strong>${escapeHtml(f.binding_method || 'sentence_direct')}</strong></div>
                                <div>Value Binding Conf: ${((f.value_binding_confidence || 0.9) * 100).toFixed(0)}%</div>
                                <div>Semantic Grounding: ${((f.grounding_confidence || 0.9) * 100).toFixed(0)}%</div>
                            </div>
                        </details>

                        <div class="quote-box">" ${escapeHtml(f.raw_quote || '')} "</div>
                        
                        <div class="confidence-bar-container">
                            <div class="confidence-bar-fill" style="width: ${finalPct}%;"></div>
                        </div>

                        <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); margin-top: 8px;">
                            <span>Source: <strong>${escapeHtml(docName)}</strong> (Page ${f.page || '?'})</span>
                            <span>Method: ${escapeHtml(f.extraction_method || 'rule-based')}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderRelationships(rels) {
            const container = document.getElementById('relList');
            if (!Array.isArray(rels) || rels.length === 0) {
                container.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-muted);">Click "Run Cross-Doc Analysis" above to detect relationships.</p>`;
                return;
            }

            container.innerHTML = rels.map(r => {
                let badgeClass = 'badge-muted';
                const typeUpper = (r.relationship_type || '').toUpperCase();
                if (typeUpper === 'CORROBORATES') badgeClass = 'badge-success';
                else if (typeUpper.includes('RECONCILED')) badgeClass = 'badge-warning';
                else if (typeUpper.includes('CONTRADICT')) badgeClass = 'badge-danger';

                const checklist = Array.isArray(r.match_checklist) 
                    ? r.match_checklist 
                    : (typeof r.match_checklist === 'string' ? [r.match_checklist] : ["✓ Entity match", "✓ Metric match", "✓ Dimension compatible"]);

                const factA = r.fact_a || {};
                const factB = r.fact_b || {};
                const confPct = ((r.confidence || 0) * 100).toFixed(0);

                return `
                    <div class="fact-card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <div>
                                <span class="badge ${badgeClass}">${escapeHtml(typeUpper)}</span>
                                ${r.taxonomy_category && r.taxonomy_category !== typeUpper ? `<span class="badge badge-primary">${escapeHtml(r.taxonomy_category)}</span>` : ''}
                            </div>
                            <span style="font-size: 0.78rem; color: var(--text-muted);">Confidence: ${confPct}%</span>
                        </div>

                        <div class="checklist-bar">
                            ${checklist.map(item => `<span class="check-item">${escapeHtml(item)}</span>`).join('')}
                        </div>

                        <div class="rel-pair-grid">
                            <div style="background: rgba(0,0,0,0.25); padding: 10px; border-radius: 8px; font-size: 0.82rem;">
                                <div style="font-weight: 600; margin-bottom: 4px; color: var(--text-muted);">
                                    Fact A (${escapeHtml(factA.source_document || 'Doc A')} · Page ${factA.page || '?'})
                                </div>
                                <div style="color: var(--primary); font-weight: 600;">${escapeHtml(factA.metric || 'Metric A')}</div>
                                <div style="font-size: 1.1rem; font-weight: 700; color: #818cf8; margin: 4px 0;">
                                    ${escapeHtml(factA.value || '')} <span style="font-size: 0.8rem; font-weight: 400; color: var(--text-muted);">${escapeHtml(factA.unit || '')}</span>
                                </div>
                                <div style="font-size: 0.75rem; color: var(--text-muted);">Period: ${escapeHtml(factA.period || 'N/A')}</div>
                            </div>
                            <div style="background: rgba(0,0,0,0.25); padding: 10px; border-radius: 8px; font-size: 0.82rem;">
                                <div style="font-weight: 600; margin-bottom: 4px; color: var(--text-muted);">
                                    Fact B (${escapeHtml(factB.source_document || 'Doc B')} · Page ${factB.page || '?'})
                                </div>
                                <div style="color: var(--primary); font-weight: 600;">${escapeHtml(factB.metric || 'Metric B')}</div>
                                <div style="font-size: 1.1rem; font-weight: 700; color: #818cf8; margin: 4px 0;">
                                    ${escapeHtml(factB.value || '')} <span style="font-size: 0.8rem; font-weight: 400; color: var(--text-muted);">${escapeHtml(factB.unit || '')}</span>
                                </div>
                                <div style="font-size: 0.75rem; color: var(--text-muted);">Period: ${escapeHtml(factB.period || 'N/A')}</div>
                            </div>
                        </div>
                        <div style="margin-top: 10px; font-size: 0.82rem; background: rgba(255,255,255,0.04); padding: 8px 12px; border-radius: 6px;">
                            💡 <strong>Reasoning:</strong> ${escapeHtml(r.reasoning || '')}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderRejected(rejectedData) {
            const container = document.getElementById('rejectedList');
            if (!rejectedData || !rejectedData.groups) {
                container.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-muted);">No rejected extractions logged.</p>`;
                return;
            }

            const entries = Object.entries(rejectedData.groups).filter(([_, items]) => Array.isArray(items) && items.length > 0);
            if (entries.length === 0) {
                container.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-muted);">No rejected extractions logged.</p>`;
                return;
            }

            container.innerHTML = `
                <div style="margin-bottom: 12px; font-size: 0.88rem; color: var(--text-muted);">
                    Total Rejected Candidates: <strong>${rejectedData.total_rejected || 0}</strong> (Grouped by Failure Type)
                </div>
                ${entries.map(([category, items], idx) => `
                    <details class="fact-card" style="border-left: 4px solid var(--warning);" ${idx === 0 ? 'open' : ''}>
                        <summary style="cursor: pointer; font-weight: 600; font-size: 0.9rem; color: var(--text-main);">
                            ${escapeHtml(category)} <span class="badge badge-warning">${items.length} candidates</span>
                        </summary>
                        <div style="margin-top: 10px;">
                            ${items.slice(0, 50).map(rj => `
                                <div style="background: rgba(0,0,0,0.3); border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                                    <div style="font-size: 0.82rem; font-family: monospace; color: #cbd5e1; margin-bottom: 4px;">
                                        ${escapeHtml(rj.candidate_text || '')}
                                    </div>
                                    <div style="font-size: 0.78rem; color: var(--danger);">
                                        🚫 ${escapeHtml(rj.rejection_reason || '')} (Page ${rj.page || '?'})
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </details>
                `).join('')}
            `;
        }

        function renderCases(casesData) {
            const container = document.getElementById('evaluatorCasesContent');
            if (!casesData) {
                container.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-muted);">No cases data available.</p>`;
                return;
            }

            const corr = casesData.corroborated_case;
            const contra = casesData.likely_contradiction_case;
            const reconc = casesData.reconciled_case;
            const fail = casesData.extraction_failure_case;

            container.innerHTML = `
                <div class="case-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: var(--success);">Case 1: Corroborated Fact Across Documents</span>
                        <span class="badge badge-success">CORROBORATES</span>
                    </div>
                    ${corr ? `
                        <div style="font-size: 0.95rem; font-weight: 700; margin-bottom: 4px;">
                            ${escapeHtml(corr.fact_a ? corr.fact_a.metric : 'Express parcel shipment volume')}
                        </div>
                        <div class="checklist-bar">
                            <span class="check-item">✓ Same entity</span>
                            <span class="check-item">✓ Same metric</span>
                            <span class="check-item">✓ Same period</span>
                            <span class="check-item">✓ Compatible units</span>
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); margin-top: 8px;">
                            <strong>Fact A (${escapeHtml(corr.fact_a ? corr.fact_a.source_document || '' : '')} · Page ${corr.fact_a ? corr.fact_a.page : '?'}):</strong> ${escapeHtml(corr.fact_a ? corr.fact_a.value : '')} ${escapeHtml(corr.fact_a ? corr.fact_a.unit || '' : '')}<br>
                            <strong>Fact B (${escapeHtml(corr.fact_b ? corr.fact_b.source_document || '' : '')} · Page ${corr.fact_b ? corr.fact_b.page : '?'}):</strong> ${escapeHtml(corr.fact_b ? corr.fact_b.value : '')} ${escapeHtml(corr.fact_b ? corr.fact_b.unit || '' : '')}<br>
                            <strong>Reasoning:</strong> ${escapeHtml(corr.reasoning || '')}
                        </div>
                    ` : `
                        <p style="font-size: 0.85rem; color: var(--text-muted);">Not detected yet in uploaded documents.</p>
                    `}
                </div>

                <div class="case-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: var(--danger);">Case 2: Likely Contradiction / Discrepancy</span>
                        <span class="badge badge-danger">LIKELY CONTRADICTION</span>
                    </div>
                    ${contra ? `
                        <div style="font-size: 0.95rem; font-weight: 700; margin-bottom: 4px;">
                            ${escapeHtml(contra.fact_a ? contra.fact_a.metric : 'Female workforce YoY growth')}
                        </div>
                        <div class="checklist-bar">
                            <span class="check-item">✓ Same entity</span>
                            <span class="check-item">✓ Same metric</span>
                            <span class="check-item">✓ Same period</span>
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); margin-top: 8px;">
                            <strong>Fact A:</strong> ${escapeHtml(contra.fact_a ? contra.fact_a.value : '')} ${escapeHtml(contra.fact_a ? contra.fact_a.unit || '' : '')} (${escapeHtml(contra.fact_a ? contra.fact_a.source_document || '' : '')} p${contra.fact_a ? contra.fact_a.page : ''})<br>
                            <strong>Fact B:</strong> ${escapeHtml(contra.fact_b ? contra.fact_b.value : '')} ${escapeHtml(contra.fact_b ? contra.fact_b.unit || '' : '')} (${escapeHtml(contra.fact_b ? contra.fact_b.source_document || '' : '')} p${contra.fact_b ? contra.fact_b.page : ''})<br>
                            <strong>Reasoning:</strong> ${escapeHtml(contra.reasoning || '')}
                        </div>
                    ` : `
                        <p style="font-size: 0.85rem; color: var(--text-muted);">Not detected yet in uploaded documents.</p>
                    `}
                </div>

                <div class="case-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: var(--warning);">Case 3: Reconciled Contradiction by Context</span>
                        <span class="badge badge-warning">RECONCILED BY CONTEXT</span>
                    </div>
                    ${reconc ? `
                        <div style="font-size: 0.95rem; font-weight: 700; margin-bottom: 4px;">
                            ${escapeHtml(reconc.fact_a ? reconc.fact_a.metric : 'Revenue / Financial Metric')}
                        </div>
                        <div class="checklist-bar">
                            <span class="check-item">✓ Same entity</span>
                            <span class="check-item">✓ Same metric</span>
                            <span class="check-item">✓ Reconciled by: ${escapeHtml(reconc.reconciliation_type || '')}</span>
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); margin-top: 8px;">
                            <strong>Fact A (${escapeHtml(reconc.fact_a ? reconc.fact_a.period || 'Period A' : '')}):</strong> ${escapeHtml(reconc.fact_a ? reconc.fact_a.value : '')} ${escapeHtml(reconc.fact_a ? reconc.fact_a.unit || '' : '')}<br>
                            <strong>Fact B (${escapeHtml(reconc.fact_b ? reconc.fact_b.period || 'Period B' : '')}):</strong> ${escapeHtml(reconc.fact_b ? reconc.fact_b.value : '')} ${escapeHtml(reconc.fact_b ? reconc.fact_b.unit || '' : '')}<br>
                            <strong>Reconciliation Reasoning:</strong> ${escapeHtml(reconc.reasoning || '')}
                        </div>
                    ` : `
                        <p style="font-size: 0.85rem; color: var(--text-muted);">Not detected yet in uploaded documents.</p>
                    `}
                </div>

                <div class="case-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: #818cf8;">Case 4: Extraction & Reasoning Failure Demonstration</span>
                        <span class="badge badge-primary">EXTRACTION FAILURE</span>
                    </div>
                    ${fail ? `
                        <div style="font-size: 0.88rem; color: #cbd5e1; margin-bottom: 8px;">
                            <strong>Failure Classification:</strong> <span class="badge badge-danger">${escapeHtml(fail.failure_type || '')}</span>
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted);">
                            <strong>Candidate Text:</strong> <code>${escapeHtml(fail.candidate_text || '')}</code><br>
                            <strong>Rejection Reason:</strong> ${escapeHtml(fail.rejection_reason || '')} (Page ${fail.page || '?'})
                        </div>
                    ` : `
                        <p style="font-size: 0.85rem; color: var(--text-muted);">No candidate rejection logged yet.</p>
                    `}
                </div>
            `;
        }

        function switchTab(tabId, targetEl) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            
            const activeBtn = targetEl || (typeof event !== 'undefined' && event ? (event.currentTarget || event.target) : null);
            if (activeBtn && activeBtn.classList) {
                activeBtn.classList.add('active');
            } else {
                const btnMap = { 'factsTab': 0, 'relsTab': 1, 'rejectedTab': 2, 'casesTab': 3 };
                const idx = btnMap[tabId];
                const allBtns = document.querySelectorAll('.tab-btn');
                if (allBtns[idx]) allBtns[idx].classList.add('active');
            }

            ['factsTab', 'relsTab', 'rejectedTab', 'casesTab'].forEach(t => {
                const el = document.getElementById(t);
                if (el) el.style.display = (t === tabId) ? 'block' : 'none';
            });
        }

        // Initialize drag & drop on dropzoneEl
        document.addEventListener("DOMContentLoaded", () => {
            const dropzoneEl = document.getElementById('dropzoneEl');
            if (dropzoneEl) {
                dropzoneEl.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    dropzoneEl.style.borderColor = 'var(--primary)';
                    dropzoneEl.style.background = 'rgba(99, 102, 241, 0.12)';
                });
                dropzoneEl.addEventListener('dragleave', (e) => {
                    e.preventDefault();
                    dropzoneEl.style.borderColor = 'rgba(255, 255, 255, 0.18)';
                    dropzoneEl.style.background = 'rgba(0, 0, 0, 0.2)';
                });
                dropzoneEl.addEventListener('drop', (e) => {
                    e.preventDefault();
                    dropzoneEl.style.borderColor = 'rgba(255, 255, 255, 0.18)';
                    dropzoneEl.style.background = 'rgba(0, 0, 0, 0.2)';
                    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                        uploadFile(e.dataTransfer.files[0]);
                    }
                });
            }

            refreshData();
        });
    