from flask import Flask, request, send_file, jsonify, send_from_directory
from flask_cors import CORS
import os
import tempfile
import zipfile
from osgeo import ogr
import shutil
import sys

app = Flask(__name__, static_folder='static')
CORS(app)

# Serve frontend
@app.route('/')
def serve_frontend():
    return send_from_directory('static', 'index.html')

# API endpoint for conversion
@app.route('/convert-to-gdb', methods=['POST'])
def convert_to_gdb():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files['file']
    if uploaded_file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        gpx_path = os.path.join(temp_dir, "input.gpx")
        uploaded_file.save(gpx_path)

        # Create File Geodatabase
        gdb_name = os.path.splitext(uploaded_file.filename)[0] + ".gdb"
        gdb_path = os.path.join(temp_dir, gdb_name)
        
        # Convert using GDAL/OGR
        if not convert_gpx_to_gdb(gpx_path, gdb_path):
            return jsonify({"error": "Conversion failed"}), 500

        # Zip the GDB folder
        zip_path = os.path.join(temp_dir, gdb_name + ".zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(gdb_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

        return send_file(zip_path, as_attachment=True, download_name=gdb_name + ".zip")

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Cleanup
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)

def convert_gpx_to_gdb(gpx_path, output_gdb):
    try:
        # Enable GDAL exceptions
        ogr.UseExceptions()
        
        # Verify GPX file exists
        if not os.path.exists(gpx_path):
            raise FileNotFoundError(f"GPX file not found: {gpx_path}")
            
        # Create output directory
        os.makedirs(os.path.dirname(output_gdb), exist_ok=True)
        
        # Create File Geodatabase
        driver = ogr.GetDriverByName("FileGDB") or ogr.GetDriverByName("OpenFileGDB")
        if driver is None:
            raise RuntimeError("No suitable GDB driver available")
            
        # Remove existing GDB if it exists
        if os.path.exists(output_gdb):
            driver.DeleteDataSource(output_gdb)
            
        gdb_ds = driver.CreateDataSource(output_gdb)
        if gdb_ds is None:
            raise RuntimeError(f"Failed to create GDB at {output_gdb}")
        
        # Open GPX file
        gpx_ds = ogr.Open(gpx_path)
        if gpx_ds is None:
            raise RuntimeError(f"Failed to open GPX file: {gpx_path}")
            
        # Process all layers
        for i in range(gpx_ds.GetLayerCount()):
            layer = gpx_ds.GetLayerByIndex(i)
            if layer.GetFeatureCount() == 0:
                continue
                
            # Create layer in GDB
            out_layer = gdb_ds.CreateLayer(
                layer.GetName(),
                geom_type=layer.GetGeomType()
            )
            
            if out_layer is None:
                continue
                
            # Copy fields
            layer_defn = layer.GetLayerDefn()
            for i in range(layer_defn.GetFieldCount()):
                out_layer.CreateField(layer_defn.GetFieldDefn(i))
                
            # Copy features
            feature = layer.GetNextFeature()
            while feature:
                new_feature = ogr.Feature(out_layer.GetLayerDefn())
                new_feature.SetFrom(feature)
                out_layer.CreateFeature(new_feature)
                feature = layer.GetNextFeature()
                
        return True
        
    except Exception as e:
        print(f"Conversion error: {str(e)}", file=sys.stderr)
        return False
    finally:
        # Cleanup
        if 'gpx_ds' in locals():
            gpx_ds = None
        if 'gdb_ds' in locals():
            gdb_ds = None

if __name__ == '__main__':
    # Create static directory if it doesn't exist
    os.makedirs('static', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)