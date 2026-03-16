#!/usr/bin/env python3
"""
RAG experiment CLI.

Commands:
    index    [--strategy fixed|structure|both]
    search   --query "..." [--strategy fixed|structure|both] [--top-k N]
    compare
    stats
"""

import argparse
import sys
from pathlib import Path

# Allow running from repo root: python3 experiments/rag_compare/cli.py
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from deepseek_chat.core.rag.config import load_rag_config
from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
from deepseek_chat.core.rag.pipeline import run_pipeline
from deepseek_chat.core.rag.store import get_stats, search_by_embedding
from experiments.rag_compare.compare import compare_strategies, print_report, save_report


def cmd_index(args: argparse.Namespace) -> None:
    config = load_rag_config()
    results = run_pipeline(strategy=args.strategy, config=config, verbose=True)
    print("\nIndex summary:")
    for r in results:
        status = "ok" if not r.errors else f"{len(r.errors)} errors"
        print(f"  [{r.strategy}] {r.total_chunks} chunks  {r.elapsed_seconds:.1f}s  {status}")


def cmd_search(args: argparse.Namespace) -> None:
    config = load_rag_config()
    embedder = OllamaEmbeddingClient(config)

    print(f"Query: {args.query!r}")
    vec = embedder.embed([args.query])[0]

    strategies = ["fixed", "structure"] if args.strategy == "both" else [args.strategy]
    for strat in strategies:
        results = search_by_embedding(
            vec, top_k=args.top_k, strategy=strat, db_path=config.db_path
        )
        print(f"\n── {strat.upper()} (top {args.top_k}) ─────────────────────")
        for i, r in enumerate(results, 1):
            section = f"  section: {r['section']}" if r.get("section") else ""
            print(f"\n{i}. score={r['score']:.4f}  [{r['title']}]{section}")
            print(f"   source : {Path(r['source']).name}")
            preview = r["text"][:200].replace("\n", " ")
            print(f"   text   : {preview}...")


def cmd_compare(args: argparse.Namespace) -> None:
    config = load_rag_config()
    report = compare_strategies(config=config)
    print_report(report)
    path = save_report(report)
    print(f"\nReport saved to: {path}")


def cmd_stats(args: argparse.Namespace) -> None:
    config = load_rag_config()
    stats = get_stats(config.db_path)
    print(f"Index: {config.db_path}")
    print(f"Total chunks : {stats['total']}")
    for strat, cnt in stats["per_strategy"].items():
        print(f"  [{strat}] {cnt} chunks")
    if stats["last_indexed_at"]:
        print(f"Last indexed : {stats['last_indexed_at']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG experiment — document indexing and strategy comparison"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = sub.add_parser("index", help="Index corpus documents")
    p_index.add_argument(
        "--strategy",
        choices=["fixed", "structure", "both"],
        default="both",
    )

    # search
    p_search = sub.add_parser("search", help="Semantic search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument(
        "--strategy",
        choices=["fixed", "structure", "both"],
        default="both",
    )
    p_search.add_argument("--top-k", type=int, default=3, dest="top_k")

    # compare
    sub.add_parser("compare", help="Compare chunking strategies on probe queries")

    # stats
    sub.add_parser("stats", help="Show index statistics")

    args = parser.parse_args()

    dispatch = {
        "index": cmd_index,
        "search": cmd_search,
        "compare": cmd_compare,
        "stats": cmd_stats,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
