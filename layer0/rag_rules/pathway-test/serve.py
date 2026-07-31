import pathway as pw
from pathway.xpacks.llm.document_store import DocumentStore
from pathway.xpacks.llm.parsers import UnstructuredParser
from pathway.xpacks.llm.splitters import TokenCountSplitter
from pathway.xpacks.llm.embedders import SentenceTransformerEmbedder
from pathway.xpacks.llm.servers import DocumentStoreServer
from pathway.stdlib.indexing.nearest_neighbors import BruteForceKnnFactory

from india_rules import get_rules_as_pathway_table

def main():

    # ── SOURCE 1: PDFs ──────────────────────────────────
    raw_docs = pw.io.fs.read(
        "./data/policy_docs/",
        format="binary",
        mode="streaming",
        with_metadata=True
    )

    # ── SOURCE 2: Hardcoded Indian rules ────────────────
    rules_table = get_rules_as_pathway_table()

    # ── MERGE both sources ───────────────────────────────
    all_docs = pw.Table.concat_reindex(raw_docs, rules_table)

    embedder = SentenceTransformerEmbedder(model="all-MiniLM-L6-v2")

    retriever_factory = BruteForceKnnFactory(embedder=embedder)

    doc_store = DocumentStore(
        docs=all_docs,
        retriever_factory=retriever_factory,
        parser=UnstructuredParser(),
        splitter=TokenCountSplitter(max_tokens=512),
    )

    server = DocumentStoreServer(
        host="0.0.0.0",
        port=8765,
        document_store=doc_store,
    )
    server.run()

if __name__ == "__main__":
    main()