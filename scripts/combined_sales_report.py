import pandas as pd
import glob
import os

def combine_isbn_reports(file_pattern, output_filename="combined_sales_report.csv"):
    """
    Combines CSV files based on a file pattern, sums 'QTY' by 'ISBN', 
    and saves the result to a new CSV.
    
    Args:
        file_pattern (str or list): Either a list of file paths or a 
                                    glob pattern like 'NYT_*.csv'.
        output_filename (str): The name of the combined output file.
    """
    # Get the list of files to process
    if isinstance(file_pattern, str):
        file_list = glob.glob(file_pattern)
    else:
        file_list = file_pattern
        
    if not file_list:
        print("No files found matching the provided pattern.")
        return

    combined_data = []

    for file in file_list:
        try:
            # Read the CSV file
            df = pd.read_csv(file)
            
            # Ensure the required columns exist (ISBN and QTY)
            if 'ISBN' in df.columns and 'QTY' in df.columns:
                # Store only the necessary columns
                combined_data.append(df[['ISBN', 'QTY']])
                print(f"Processed: {file}")
            else:
                print(f"Skipping {file}: Missing 'ISBN' or 'QTY' column.")
        except Exception as e:
            print(f"Error reading {file}: {e}")

    if combined_data:
        # Concatenate all dataframes into one
        all_sales = pd.concat(combined_data, ignore_index=True)
        
        # Group by ISBN and sum the QTY
        final_report = all_sales.groupby('ISBN', as_index=False)['QTY'].sum()
        
        # Save the result to a new CSV
        final_report.to_csv(output_filename, index=False)
        print(f"\nSuccessfully combined {len(file_list)} files.")
        print(f"Output saved to: {output_filename}")
        return final_report
    else:
        print("No valid data was found to combine.")

# Example usage:
# files_to_process = ["report1.csv", "report2.csv"]
# combine_isbn_reports(files_to_process, "final_combined_output.csv")