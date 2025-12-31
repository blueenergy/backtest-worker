#!/usr/bin/env python3
"""
Setup script to copy visualization and reporting modules from stock-execution-system.

This script copies the plotting and reporting modules from stock-execution-system
to make the local backtest runner fully functional with advanced visualizations.
"""

import shutil
from pathlib import Path


def copy_visualization_modules():
    """Copy plotting and reporting modules from stock-execution-system."""
    
    # Source directories from stock-execution-system
    source_plotting = Path("/Users/shuyonglin/code/stock-execution-system/shared/utils/plotting.py")
    source_reporting = Path("/Users/shuyonglin/code/stock-execution-system/shared/utils/reporting.py")
    
    # Destination in backtest-worker
    dest_dir = Path(__file__).parent / "visualization"
    dest_dir.mkdir(exist_ok=True)
    
    dest_plotting = dest_dir / "plotting.py"
    dest_reporting = dest_dir / "reporting.py"
    
    print("📋 Copying visualization modules from stock-execution-system...")
    
    # Copy plotting module
    if source_plotting.exists():
        shutil.copy2(source_plotting, dest_plotting)
        print(f"✅ Copied plotting module to: {dest_plotting}")
    else:
        print(f"❌ Source plotting module not found: {source_plotting}")
        return False
    
    # Copy reporting module
    if source_reporting.exists():
        shutil.copy2(source_reporting, dest_reporting)
        print(f"✅ Copied reporting module to: {dest_reporting}")
    else:
        print(f"❌ Source reporting module not found: {source_reporting}")
        return False
    
    # Create __init__.py to make it a package
    init_file = dest_dir / "__init__.py"
    init_file.write_text('"""Visualization package for backtest worker."""\n')
    print(f"✅ Created package init file: {init_file}")
    
    print("\n📊 Visualization modules copied successfully!")
    print(f"📁 You can now import plotting and reporting from: {dest_dir}")
    print("🔧 The local backtest runner will automatically use these modules for advanced visualizations")
    
    return True


def update_run_local_backtest_imports():
    """Update the run_local_backtest.py to use local visualization modules."""
    
    run_local_script = Path(__file__).parent / "run_local_backtest.py"
    
    if not run_local_script.exists():
        print(f"❌ run_local_backtest.py not found: {run_local_script}")
        return False
    
    content = run_local_script.read_text()
    
    # Update import paths to use local visualization modules
    if "from visualization.plotting import plot_symbol_close" not in content:
        # Replace the stock-execution-system import with local import
        new_content = content.replace(
            "sys.path.insert(0, '/Users/shuyonglin/code/stock-execution-system')\n        from shared.utils.plotting import plot_symbol_close",
            "from visualization.plotting import plot_symbol_close"
        )
        
        new_content = new_content.replace(
            "from shared.utils.reporting import generate_quantstats_report",
            "from visualization.reporting import generate_quantstats_report"
        )
        
        # Write updated content
        run_local_script.write_text(new_content)
        print("✅ Updated run_local_backtest.py to use local visualization modules")
    
    return True


def main():
    """Main entry point."""
    print("🚀 Setting up visualization modules for backtest worker...")
    print("=" * 60)
    
    success = copy_visualization_modules()
    
    if success:
        success = update_run_local_backtest_imports()
    
    if success:
        print("=" * 60)
        print("🎉 Setup completed successfully!")
        print("\n💡 You can now run local backtests with advanced visualizations:")
        print("   python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231")
        print("\n📊 The results will include:")
        print("   • Equity curve plots with trade markers")
        print("   • Trade execution tables")
        print("   • HTML performance reports using quantstats")
        print("   • Portfolio visualization vs individual stocks")
    else:
        print("=" * 60)
        print("❌ Setup failed. Please check the error messages above.")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())