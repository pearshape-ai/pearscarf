"""One-time migration: add temporal timestamps to existing graph data.

Sets valid_at = created_at and invalid_at = null on all edges and facts
that don't already have temporal timestamps. Safe to run multiple times.
"""

from pearscaff.graph import retrofit_temporal

if __name__ == "__main__":
    print("Retrofitting temporal timestamps on existing graph data...")
    result = retrofit_temporal()
    print(
        f"Done: {result['edges_retrofitted']} edges retrofitted, "
        f"{result['facts_retrofitted']} facts retrofitted"
    )
