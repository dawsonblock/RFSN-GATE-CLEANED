"""Migration utilities for learning data persistence.

Provides tools for migrating learning data between persistence backends,
particularly from SQLite (development) to PostgreSQL (production).
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TextIO

from .backends import Backend, create_backend

logger = logging.getLogger(__name__)


def migrate(
    source: Backend,
    target: Backend,
    tables: list[str] | None = None,
    dry_run: bool = False,
    progress_callback: callable | None = None,
) -> dict:
    """Migrate data from source backend to target backend.
    
    Args:
        source: Source backend to read from
        target: Target backend to write to
        tables: Specific tables to migrate, or None for all
        dry_run: If True, don't actually write to target
        progress_callback: Optional callback for progress updates
    
    Returns:
        Migration statistics dict with keys:
        - tables: Number of tables migrated
        - records: Total records migrated
        - errors: Number of errors encountered
    """
    stats = {"tables": 0, "records": 0, "errors": 0}
    
    # Discover tables if not specified
    if tables is None:
        # Common tables used by learning components
        tables = ["strategy_stats", "quarantine_stats", "context_stats"]
    
    for table in tables:
        try:
            entries = source.list_all(table)
            if not entries:
                logger.info("Table '%s' is empty, skipping", table)
                continue
            
            logger.info("Migrating table '%s': %d records", table, len(entries))
            stats["tables"] += 1
            
            for entry in entries:
                try:
                    if not dry_run:
                        target.set(table, entry.key, entry.value)
                    stats["records"] += 1
                    
                    if progress_callback:
                        progress_callback(table, entry.key, stats["records"])
                except Exception as e:
                    logger.warning("Failed to migrate %s/%s: %s", table, entry.key, e)
                    stats["errors"] += 1
                    
        except Exception as e:
            logger.error("Failed to read table '%s': %s", table, e)
            stats["errors"] += 1
    
    return stats


def validate_migration(source: Backend, target: Backend, tables: list[str] | None = None) -> dict:
    """Validate that target contains all data from source.
    
    Args:
        source: Source backend
        target: Target backend  
        tables: Specific tables to validate
    
    Returns:
        Validation result dict with keys:
        - valid: True if all data matches
        - missing: List of missing keys
        - mismatched: List of keys with different values
    """
    result = {"valid": True, "missing": [], "mismatched": []}
    
    if tables is None:
        tables = ["strategy_stats", "quarantine_stats", "context_stats"]
    
    for table in tables:
        source_entries = {e.key: e.value for e in source.list_all(table)}
        
        for key, source_value in source_entries.items():
            target_value = target.get(table, key)
            
            if target_value is None:
                result["missing"].append(f"{table}/{key}")
                result["valid"] = False
            elif target_value != source_value:
                result["mismatched"].append(f"{table}/{key}")
                result["valid"] = False
    
    return result


def main(argv: list[str] | None = None, stdout: TextIO = sys.stdout) -> int:
    """CLI entry point for migration tool.
    
    Usage:
        python -m rfsn_controller.persistence.migration \\
            --source sqlite:./learning.db \\
            --target postgres:postgresql://user:pass@host/db
    """
    parser = argparse.ArgumentParser(
        description="Migrate RFSN learning data between persistence backends"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source backend (format: type:path_or_connection)",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target backend (format: type:path_or_connection)",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        help="Specific tables to migrate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without writing",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate migration after completion",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args(argv)
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Parse backend specifications
    def parse_backend_spec(spec: str) -> Backend:
        if ":" not in spec:
            raise ValueError(f"Invalid backend spec: {spec}. Expected format: type:path")
        
        backend_type, path = spec.split(":", 1)
        
        if backend_type == "sqlite":
            return create_backend("sqlite", db_path=path)
        elif backend_type in ("postgres", "postgresql"):
            return create_backend("postgres", connection_string=path)
        elif backend_type == "memory":
            return create_backend("memory")
        else:
            raise ValueError(f"Unknown backend type: {backend_type}")
    
    try:
        source = parse_backend_spec(args.source)
        target = parse_backend_spec(args.target)
    except Exception as e:
        stdout.write(f"Error parsing backend: {e}\n")
        return 1
    
    try:
        # Perform migration
        stdout.write(f"Migrating from {args.source} to {args.target}\n")
        if args.dry_run:
            stdout.write("DRY RUN - no data will be written\n")
        
        stats = migrate(
            source=source,
            target=target,
            tables=args.tables,
            dry_run=args.dry_run,
        )
        
        stdout.write(f"\nMigration complete:\n")
        stdout.write(f"  Tables: {stats['tables']}\n")
        stdout.write(f"  Records: {stats['records']}\n")
        stdout.write(f"  Errors: {stats['errors']}\n")
        
        # Validate if requested
        if args.validate and not args.dry_run:
            stdout.write("\nValidating migration...\n")
            validation = validate_migration(source, target, args.tables)
            
            if validation["valid"]:
                stdout.write("✓ Validation passed\n")
            else:
                stdout.write("✗ Validation failed\n")
                if validation["missing"]:
                    stdout.write(f"  Missing: {len(validation['missing'])} records\n")
                if validation["mismatched"]:
                    stdout.write(f"  Mismatched: {len(validation['mismatched'])} records\n")
                return 1
        
        return 0 if stats["errors"] == 0 else 1
        
    except Exception as e:
        stdout.write(f"Migration failed: {e}\n")
        return 1
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    sys.exit(main())
